/**
 * Gate §6.7 de D-GOB-15: con card la pantalla pinta «Ficha del modelo»; sin card no hay bloque.
 *
 * El runner corre en `node` —sin DOM, sin jsdom ni testing-library: el goal veta deps nuevas—, así
 * que el panel REAL se renderiza a HTML estático con `react-dom/server`, que ya es dependencia del
 * front. `ResultsPanel` recibe a mano lo que `ResultsTab` toma del store; es el mismo árbol que
 * pinta el navegador, sin provider. Lo que esto no prueba —layout, foco, el `<details>`
 * abriéndose— se verifica en la UI viva, como declara `jobs.test.ts`.
 *
 * Los fixtures de la demo se renderizan enteros (charts incluidos): traen `model_card: null` y el
 * guard por presencia los cubre sin recaptura (D-GOB-9 conserva su OK propio).
 */

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ResultsPanel, type ResultsPanelProps } from "@/components/ResultsTab"
import resultsTabSource from "@/components/ResultsTab.tsx?raw"
import demoF1 from "@/fixtures/demo/results-f1.json"
import demoF4 from "@/fixtures/demo/results-ifrs9.json"
import { MODEL_CARD_F1 } from "@/lib/model-card.fixture"
import type { ModelCard, ResultsResponse } from "@/lib/results-types"

const TITULO = "Ficha del modelo"
/** Rótulos que sólo la sección de la ficha escribe: ninguno debe sobrevivir sin card. */
const ROTULOS_DE_LA_FICHA = [
  TITULO,
  "Propósito",
  "Supuestos",
  "Limitaciones",
  "Emitida",
  "Próxima revisión",
  "Decisiones registradas",
  "Métricas por dominio",
]

// Las corridas que la demo publica hoy (D-JUR-9.7: la de provisiones CMF salió del árbol).
const DEMOS: [string, ResultsResponse][] = [
  ["results-f1.json", demoF1 as unknown as ResultsResponse],
  ["results-ifrs9.json", demoF4 as unknown as ResultsResponse],
]

function render(results: ResultsResponse | null): string {
  const props: ResultsPanelProps = {
    results,
    lastRun: null,
    validation: { kind: "idle" },
    onNavigate: () => {},
  }
  return renderToStaticMarkup(createElement(ResultsPanel, props))
}

const ocurrencias = (html: string, texto: string): number => html.split(texto).length - 1

/** Corrida mínima: sin secciones de dominio, sólo lo que decide si la ficha existe o no. */
const minima = (model_card: ModelCard | null): ResultsResponse => ({
  status: "done",
  run_id: "4b04cbdeed9a45d5b701aabbb8760eff",
  error: null,
  model_card,
})

describe("con card, el panel pinta «Ficha del modelo»", () => {
  const html = render(minima(MODEL_CARD_F1))

  it("exactamente una vez, con lo que la institución declaró", () => {
    expect(ocurrencias(html, TITULO)).toBe(1)
    expect(html).toContain(MODEL_CARD_F1.purpose)
    expect(html).toContain("La cartera sintetica es representativa del segmento.")
    expect(html).toContain("No se modela la amortizacion del credito.")
  })

  it("con las fechas de emisión y de próxima revisión, como fecha calendario", () => {
    expect(html).toContain("Emitida")
    expect(html).toContain("2026-09-03")
    expect(html).toContain("Próxima revisión")
    expect(html).toContain("2027-09-03")
  })

  it("con el resumen de métricas por dominio y la evidencia estructurada", () => {
    expect(html).toContain("Métricas por dominio")
    expect(html).toContain("Performance")
    expect(html).toContain("auc_oot")
    expect(html).toContain("0.6561")
    expect(html).toContain("discrimination · effective_deciles_by_partition")
    expect(html).toContain("desarrollo: 10 · holdout: 10 · oot: 10")
  })

  it("con el conteo de decisiones y el acceso a su detalle", () => {
    expect(html).toContain("Decisiones registradas")
    expect(html).toContain("Ver el detalle de las decisiones")
    expect(html).toContain("statsmodels_convergence")
    expect(html).toContain("aceptar_ajuste")
    // El conteo es el largo real de la lista, no un número escrito al lado.
    expect(html).toContain(`>${MODEL_CARD_F1.decisions.length}<`)
  })

  it("también en una corrida fallida, si el serializador pudo construirla", () => {
    // El serializador emite la ficha de una corrida `failed` cuando es construible; el panel
    // enseña el error y, además, la ficha: es evidencia de gobierno de lo que sí corrió.
    const html = render({ ...minima(MODEL_CARD_F1), status: "failed", error: "se cayó" })
    expect(html).toContain("La corrida terminó con fallo")
    expect(ocurrencias(html, TITULO)).toBe(1)
  })

  it("una ficha sin supuestos ni limitaciones lo dice, no deja el hueco en blanco", () => {
    const html = render(minima({ ...MODEL_CARD_F1, assumptions: [], limitations: [] }))
    expect(html).toContain("Sin supuestos declarados.")
    expect(html).toContain("Sin limitaciones declaradas.")
  })
})

describe("sin card no hay bloque, ni vacío ni fabricado", () => {
  it("con `model_card: null` ninguno de los rótulos de la ficha aparece", () => {
    const html = render(minima(null))
    for (const rotulo of ROTULOS_DE_LA_FICHA) {
      expect(ocurrencias(html, rotulo), rotulo).toBe(0)
    }
    // Y el panel sigue pintando lo suyo: la ausencia de ficha no apaga la procedencia.
    expect(html).toContain("Artefactos de la corrida")
  })

  it.each(DEMOS)("%s: el fixture de la demo trae `model_card: null` y el guard lo cubre", (_, demo) => {
    expect(demo.model_card).toBeNull()
    const html = render(demo)
    expect(ocurrencias(html, TITULO)).toBe(0)
    expect(html).toContain("Artefactos de la corrida")
  })

  it("sin resultados, el estado vacío tampoco la nombra", () => {
    const html = render(null)
    expect(html).toContain("Sin resultados todavía")
    expect(ocurrencias(html, TITULO)).toBe(0)
  })
})

describe("la ficha va inmediatamente después de «Artefactos de la corrida»", () => {
  it("es la primera sección con título sobre una corrida F1 completa", () => {
    // Con la demo F1 entera y una ficha, el primer `<h2` del panel es el de la ficha, y la
    // procedencia —que no lleva `<h2`— va antes. Las demás secciones (Discriminación, …) después.
    const demo = demoF1 as unknown as ResultsResponse
    const html = render({ ...demo, model_card: MODEL_CARD_F1 })
    const artefactos = html.indexOf("Artefactos de la corrida")
    const primerH2 = html.indexOf("<h2")
    expect(artefactos).toBeGreaterThan(-1)
    expect(primerH2).toBeGreaterThan(artefactos)
    expect(html.slice(primerH2, html.indexOf("</h2>", primerH2))).toContain(TITULO)
    expect(html.indexOf("Discriminación")).toBeGreaterThan(primerH2)
    expect(ocurrencias(html, TITULO)).toBe(1)
  })
})

describe("copy público de la ficha", () => {
  it("los rótulos no hablan en código: sin claves del payload ni marcas internas", () => {
    // Una ficha con datos neutros deja en el HTML sólo lo que la sección escribe por sí misma.
    const neutra: ModelCard = {
      ...MODEL_CARD_F1,
      purpose: "p",
      assumptions: [],
      limitations: [],
      metrics: {},
      metric_sections: {},
      decisions: [],
    }
    const html = render(minima(neutra))
    for (const codigo of [
      "model_card",
      "metric_sections",
      "review_date",
      "next_review_date",
      "nikodym.",
      "SR 11-7",
      "FALTA-DATO",
      "DATO-INSTITUCIONAL",
      "Registry",
      "JSONL",
    ]) {
      expect(html, codigo).not.toContain(codigo)
    }
    expect(ocurrencias(html, TITULO)).toBe(1)
  })
})

describe("avisos declarados en la ficha (revisión adversarial de S4)", () => {
  // La decisión REAL con la que el motor interno de provisiones deja escrita una imputación: con
  // `fail_on_falta_dato=false` un dato ausente se imputa a cero y `internal_falta_dato` lleva el
  // código de la institución en `valor`. Publicarlo mudo era el hallazgo de la revisión.
  const imputacion: ModelCard["decisions"][number] = {
    step: null,
    regla: "internal_falta_dato",
    umbral: false,
    valor: { falta_dato: ["DATO-INSTITUCIONAL"], warning_codes: ["DATO-INSTITUCIONAL"] },
    accion: "trazar_faltantes_y_avisos",
    ts: "2026-09-08T03:27:35.000000Z",
  }
  const NOTA = "Las filas marcadas con «aviso declarado»"

  it("una decisión con aviso declarado se marca y la sección explica qué significa", () => {
    const html = render(minima({ ...MODEL_CARD_F1, decisions: [imputacion] }))
    expect(ocurrencias(html, "aviso declarado")).toBeGreaterThanOrEqual(2) // la marca y la nota
    expect(html).toContain(NOTA)
    // El código no se recorta: es la evidencia, y el lector lo necesita para auditarla.
    expect(html).toContain("falta_dato: DATO-INSTITUCIONAL")
  })

  it("también cuando el aviso viene en la evidencia CT-2 del dominio", () => {
    const html = render(
      minima({
        ...MODEL_CARD_F1,
        metric_sections: {
          provisioning_internal: {
            provisioning_internal: { warning_codes: ["DATO-INSTITUCIONAL"], n_groups: 3 },
          },
        },
      }),
    )
    expect(html).toContain(NOTA)
    expect(html).toContain("provisioning_internal · warning_codes")
  })

  it("sin avisos no hay marca ni nota: no se explica una salvedad que no ocurrió", () => {
    const html = render(minima(MODEL_CARD_F1))
    expect(ocurrencias(html, "aviso declarado")).toBe(0)
    expect(html).not.toContain(NOTA)
  })

  it("la nota no atribuye una imputación que no ocurrió: un aviso puede ser sólo una salvedad", () => {
    // Segunda revisión adversarial de S4: con `require_both=False` y una sola fuente de
    // provisiones el orquestador declara «comparación incompleta» (`DATO-INSTITUCIONAL-PROV-3`)
    // y NO imputa nada; la nota general no puede afirmar «el cálculo siguió con un valor
    // imputado» para todo aviso. Lo que cada código significa lo dice la referencia, no la nota.
    const comparacionIncompleta: ModelCard["decisions"][number] = {
      step: null,
      regla: "provisioning_falta_dato",
      umbral: "require_both=False",
      valor: { falta_dato: ["DATO-INSTITUCIONAL-PROV-3"] },
      accion: "trazar_faltantes",
      ts: "2026-09-08T03:27:36.000000Z",
    }
    const html = render(minima({ ...MODEL_CARD_F1, decisions: [comparacionIncompleta] }))
    expect(html).toContain(NOTA)
    expect(html).toContain("DATO-INSTITUCIONAL-PROV-3")
    expect(html.toLowerCase()).not.toMatch(/imputa/)
  })
})

describe("guardrails del cableado (fuente)", () => {
  it("el guard es por presencia y nunca `!`", () => {
    expect(resultsTabSource).toContain(
      "{results.model_card ? <ModelCardSection card={results.model_card} /> : null}",
    )
    expect(resultsTabSource).not.toMatch(/model_card!/)
  })

  it("`ResultsTab` sigue leyendo el store y delegando en el panel que este test renderiza", () => {
    // Si alguien volviera a leer el store dentro del panel, este test renderizaría otro árbol que
    // el navegador. El wrapper es la única lectura del store del archivo.
    expect(resultsTabSource.match(/= useAppState\(\)/g)).toHaveLength(1)
    expect(resultsTabSource).toContain("<ResultsPanel")
  })
})

// ───────── capa 1 de SCORECARD-COMPLETO: panel de selección y resumen del PSI ─────────

describe("«Selección de variables» (D-SC-10) sobre la corrida real de la demo", () => {
  const demo = demoF1 as unknown as ResultsResponse
  const html = render(demo)

  it("pinta la sección una vez, con candidatas, seleccionadas y excluidas", () => {
    expect(ocurrencias(html, "Selección de variables")).toBe(1)
    expect(html).toContain("Candidatas")
    expect(html).toContain("Seleccionadas")
    expect(html).toContain("Excluidas")
  })

  it("la exclusión real de la corrida sale con su motivo en español y su detalle del motor", () => {
    // F1 excluye `segmento` por `low_iv`. El motivo se traduce; el `detail` NO se reescribe: es
    // el dato de auditoría que ata la fila al audit-trail.
    expect(html).toContain("segmento")
    expect(html).toContain("IV insuficiente")
    expect(html).toContain("iv=0.00292241 &lt; min_iv=0.02")
    expect(html).not.toContain("low_iv")
  })

  it("las bandas de IV salen en palabras, no en slugs", () => {
    expect(html).toContain("sin poder")
    expect(html).toContain("fuerte")
    // Los slugs del enum de IV no llegan a la pantalla (`none` y `medium` son subcadenas
    // demasiado comunes para buscarlas a secas; `weak`/`strong`/`suspicious` no lo son).
    for (const slug of ["weak", "strong", "suspicious"]) {
      expect(html, slug).not.toContain(slug)
    }
  })

  it("los umbrales activos llevan el rótulo del formulario y los apagados no se pintan", () => {
    expect(html).toContain("IV mínimo")
    expect(html).toContain("Umbral |rho|")
    expect(html).toContain("Umbral VIF")
    // F1 corre sin mínimos de discriminación: pintarlos como «—» inventaría un criterio.
    for (const apagado of ["AUC mínimo", "KS mínimo", "Gini mínimo"]) {
      expect(html, apagado).not.toContain(apagado)
    }
  })

  it("sin marcas de IV alto ni de inestabilidad, no se explica una salvedad que no ocurrió", () => {
    expect(html).not.toContain("Marcadas por IV alto")
    expect(html).not.toContain("Marcadas por inestabilidad")
  })

  it("va entre «Análisis por variable (WoE)» y «Escala y calibración»", () => {
    const woe = html.indexOf("Análisis por variable (WoE)")
    const seleccion = html.indexOf("Selección de variables")
    const escala = html.indexOf("Escala y calibración")
    expect(woe).toBeGreaterThan(-1)
    expect(seleccion).toBeGreaterThan(woe)
    expect(escala).toBeGreaterThan(seleccion)
  })
})

describe("«Selección de variables»: guard por presencia y avisos declarados", () => {
  const demo = demoF1 as unknown as ResultsResponse

  it("sin `selection` la sección entera desaparece, y el resto del panel sigue", () => {
    const html = render({ ...demo, selection: undefined })
    expect(ocurrencias(html, "Selección de variables")).toBe(0)
    expect(html).not.toContain("IV insuficiente")
    expect(html).toContain("Artefactos de la corrida")
    expect(html).toContain("Estabilidad del score")
  })

  it("las marcas de IV alto e inestabilidad se pintan cuando el motor las publica", () => {
    const html = render({
      ...demo,
      selection: {
        ...demo.selection!,
        high_iv_flags: ["ingreso_mensual"],
        stability_flags: ["mora_max_12m"],
      },
    })
    expect(html).toContain("Marcadas por IV alto")
    expect(html).toContain("Marcadas por inestabilidad")
    expect(html).toContain("mora_max_12m")
  })

  it("una variable forzada lo dice en la fila", () => {
    const decisions = demo.selection!.decisions!
    const html = render({
      ...demo,
      selection: {
        ...demo.selection!,
        decisions: [{ ...decisions[0], forced: "include" }, ...decisions.slice(1)],
      },
    })
    expect(html).toContain("forzada dentro")
  })
})

describe("resumen del peor PSI en «Estabilidad del score» (D-SC-12)", () => {
  const demo = demoF1 as unknown as ResultsResponse

  it("una fila por comparación, con el rótulo que el informe usa", () => {
    const html = render(demo)
    expect(ocurrencias(html, "Peor PSI entre score y PD")).toBe(2)
    expect(html).toContain("PD calibrada")
    expect(html).toContain("0.0132")
  })

  it("con la PD ganando, la banda pintada es la de la PD y no la del score", () => {
    // 🔴 El caso divergente de A1: score estable (0,05) y PD en revisión (0,12). Pintar la banda
    // del score aquí publicaría «0,1200 · Estable», que es la contradicción que la enmienda del
    // resumen PSI cerró en el informe y que la pantalla nunca llegó a mostrar.
    const html = render({
      ...demo,
      stability: {
        ...demo.stability!,
        comparisons: ["dev_vs_holdout"],
        max_psi_by_comparison: { dev_vs_holdout: 0.12 },
        psi_metric_by_comparison: { dev_vs_holdout: "pd_psi" },
        bands_by_comparison: { dev_vs_holdout: "review" },
        stability_metrics: [
          {
            metric: "score_psi",
            comparison: "dev_vs_holdout",
            feature: "score",
            value: 0.05,
            stable_threshold: 0.1,
            review_threshold: 0.25,
            band: "stable",
            action: "none",
          },
          {
            metric: "pd_psi",
            comparison: "dev_vs_holdout",
            feature: "pd",
            value: 0.12,
            stable_threshold: 0.1,
            review_threshold: 0.25,
            band: "review",
            action: "vigilar",
          },
        ],
      },
    })
    // El recorte llega hasta el cierre del `<dl>` del resumen: la leyenda que va justo debajo
    // nombra las cuatro bandas y contaminaría la aserción.
    const inicio = html.indexOf("Peor PSI entre score y PD")
    const resumen = html.slice(inicio, html.indexOf("</dl>", inicio))
    expect(resumen).toContain("PD calibrada")
    expect(resumen).toContain("0.1200")
    expect(resumen).toContain("Revisar")
    expect(resumen).not.toContain("Estable")
  })

  it("con el score ganando, la identidad pintada es el score", () => {
    const html = render({
      ...demo,
      stability: {
        ...demo.stability!,
        comparisons: ["dev_vs_oot"],
        max_psi_by_comparison: { dev_vs_oot: 0.3 },
        psi_metric_by_comparison: { dev_vs_oot: "score_psi" },
        bands_by_comparison: { dev_vs_oot: "redevelop" },
      },
    })
    const inicio = html.indexOf("Peor PSI entre score y PD")
    const resumen = html.slice(inicio, html.indexOf("</dl>", inicio))
    expect(resumen).toContain("score")
    expect(resumen).toContain("0.3000")
    expect(resumen).toContain("Redesarrollar")
    expect(ocurrencias(html, "Peor PSI entre score y PD")).toBe(1)
  })

  it("las palabras de las bandas son las aprobadas, y ningún slug llega a la pantalla", () => {
    const html = render(demo)
    expect(html).toContain("Estable")
    for (const slug of ["not_evaluable", "redevelop", "pd_psi", "score_psi"]) {
      expect(html, slug).not.toContain(slug)
    }
  })

  it("sin estabilidad no hay sección ni resumen", () => {
    const html = render({ ...demo, stability: null })
    expect(ocurrencias(html, "Estabilidad del score")).toBe(0)
    expect(ocurrencias(html, "Peor PSI entre score y PD")).toBe(0)
  })
})
