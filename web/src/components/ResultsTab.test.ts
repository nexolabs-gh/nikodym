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
import { EDA_SCORECARD_REAL } from "@/lib/eda.fixture"
import { MODEL_CARD_F1 } from "@/lib/model-card.fixture"
import type {
  EdaResult,
  ModelCard,
  ResultsResponse,
  ValidationCalibrationRow,
  ValidationNotEvaluableGrade,
  ValidationResult,
} from "@/lib/results-types"
import { VALIDATION_F1 } from "@/lib/validation.fixture"

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

  it("una corrida vieja sin identidad no recibe semáforo: se declara y se conservan las series", () => {
    // 🔴 Hallazgo de la revisión adversarial de S8. La card legacy trae el peor valor entre score
    // y PD (0,12, que es el de la PD) con la banda del score (`stable`). El resumen no puede
    // atribuirlo, así que no lo pinta: lo dice. Sin esto la pantalla publicaría «0,1200 · Estable»,
    // que es la contradicción que la enmienda del resumen PSI cerró en el informe.
    const html = render({
      ...demo,
      stability: {
        ...demo.stability!,
        comparisons: ["dev_vs_holdout"],
        max_psi_by_comparison: { dev_vs_holdout: 0.12 },
        psi_metric_by_comparison: null,
        bands_by_comparison: { dev_vs_holdout: "stable" },
      },
    })
    expect(ocurrencias(html, "Peor PSI entre score y PD")).toBe(0)
    expect(html).not.toContain("0.1200")
    expect(html).toContain("no se puede atribuir")
    expect(html).toContain("Dev vs Holdout")
    // La sección sigue existiendo con sus series: lo que se omite es el semáforo agregado.
    expect(html).toContain("Estabilidad del score")
    expect(html).toContain("PSI del score")
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

describe("«Validación formal» (D-SC-9) sobre una corrida real", () => {
  const conValidacion = (validation: ValidationResult | null): ResultsResponse => ({
    ...(demoF1 as unknown as ResultsResponse),
    validation,
  })

  it("publica el estado técnico del motor tal cual, aunque sea «Falla»", () => {
    const html = render(conValidacion(VALIDATION_F1))
    expect(html).toContain("Validación formal")
    expect(html).toContain("Estado técnico")
    expect(html).toContain("Falla")
    // El conteo del motor, sin recalcular: 1 de 3 pruebas fallidas.
    expect(html).toContain("1 de 3")
    // Y las palabras viejas del informe no sobreviven en ninguna parte de la pantalla.
    expect(html).not.toContain("Pass técnico")
    expect(html).not.toContain("Falla técnica")
  })

  it("una sección por familia corrida, con su tabla y sin las que no corrieron", () => {
    const html = render(conValidacion(VALIDATION_F1))
    expect(html).toContain("Discriminación")
    expect(html).toContain("Calibración por muestra")
    expect(html).toContain("Hosmer-Lemeshow")
    expect(html).toContain("Puntaje de Brier")
    expect(html).toContain("Reusada de la etapa de desempeño")
    // El backtesting no está en `families_run` y su tabla llega vacía: no se pinta. ⚠️ Se busca
    // el TÍTULO con su marcado (`Subchart` pinta un `<p>`), no la palabra suelta: «backtesting»
    // aparece en la descripción de la sección, así que una aserción sobre la palabra suelta sería vacua.
    expect(html).not.toContain(">Backtesting</p>")
  })

  it("con backtesting corrido, su tabla sí aparece (ancla de la aserción de arriba)", () => {
    // 🔴 Sin este control positivo, «no aparece Backtesting» pasaría también si el panel entero
    // hubiera dejado de pintar tablas. Es el mismo cuidado que exige un control negativo: hay que
    // comprobar que la aserción puede fallar.
    const html = render(
      conValidacion({
        ...VALIDATION_F1,
        families_run: [...VALIDATION_F1.families_run, "backtesting"],
        backtesting: [
          {
            parameter: "lgd",
            segment: "consumo",
            n: 240,
            predicted_mean: 0.41,
            realised_mean: 0.47,
            test: "t_test",
            statistic: 2.1,
            p_value: 0.018,
            alpha: 0.05,
            one_sided: true,
            decision: "fail",
          },
        ],
      }),
    )
    expect(html).toContain(">Backtesting</p>")
    expect(html).toContain("Severidad")
    expect(html).toContain("t de Student")
  })

  it("el puntaje de Brier no finge un veredicto de pasa/falla", () => {
    // Es una fila `not_evaluable` por razones de forma —un puntaje no es un test—, no por falta
    // de potencia. La palabra tiene que servir para las dos cosas sin mentir en ninguna.
    const html = render(conValidacion(VALIDATION_F1))
    expect(html).toContain("Sin veredicto")
  })

  it("los avisos declarados se marcan, pero su código no se publica", () => {
    // AGENTS.md §copy público y D-SC-9: el identificador con el que el motor transporta la
    // salvedad es dato de auditoría, no una frase. Viaja entero en la card y en el anexo; aquí
    // sólo tiene que verse que hay salvedades y dónde se leen.
    const html = render(
      conValidacion({
        ...VALIDATION_F1,
        falta_dato: ["FALTA-DATO-VAL-2", "FALTA-DATO-VAL-3"],
      }),
    )
    expect(html).toContain("2 salvedades declaradas")
    expect(html).toContain("aviso declarado")
    expect(html).not.toContain("FALTA-DATO")
    expect(html).not.toContain("DATO-INSTITUCIONAL")
  })

  it("sin salvedades no hay nota, ni vacía ni fabricada", () => {
    const html = render(conValidacion({ ...VALIDATION_F1, falta_dato: [] }))
    expect(html).not.toContain("salvedad declarada")
    expect(html).not.toContain("salvedades declaradas")
  })

  it("una familia pedida que no publicó nada se dice, no se calla", () => {
    // 🔴 Verificado contra el motor: con el backtesting encendido, sin los artefactos de IFRS 9 y
    // con la parada por brechas apagada, el evaluador registra el aviso, omite la prueba y la
    // corrida termina en «Pasa» con `families_run` incluyendo `backtesting` y cero filas. Sin esta
    // nota el panel presentaría como ejecutado algo que no publicó una sola línea (§5).
    const html = render(
      conValidacion({
        ...VALIDATION_F1,
        families_run: ["stability", "backtesting"],
        overall_status: "pass",
        n_tests: 0,
        n_failed: 0,
        discrimination: [],
        calibration: [],
        backtesting: [],
        falta_dato: ["DATO-INSTITUCIONAL: falta el artefacto para el backtesting."],
      }),
    )
    expect(html).toContain("Esta familia se pidió y no publicó ninguna prueba")
    expect(html).toContain("Backtesting")
    // Y el contador no finge que hubo pruebas y todas pasaron.
    expect(html).toContain("Sin pruebas de pasa o falla")
    expect(html).not.toContain("0 de 0")
  })

  it("con todas las familias publicando filas, la nota no aparece", () => {
    // Ancla del control de arriba: «no publicó nada» tiene que poder ser falso.
    const html = render(conValidacion(VALIDATION_F1))
    expect(html).not.toContain("no publicó ninguna prueba")
    expect(html).not.toContain("Sin pruebas de pasa o falla")
    expect(html).toContain("1 de 3")
  })

  it("sin `validation` el panel entero desaparece, no queda vacío", () => {
    const html = render(conValidacion(null))
    expect(html).not.toContain("Validación formal")
    expect(html).not.toContain("Estado técnico")
    // Y la demo publicada, que se capturó ANTES de que el serializer emitiera la clave, tampoco
    // lo pinta: es el mismo guard, por presencia y no por verdad.
    const demo = render(demoF1 as unknown as ResultsResponse)
    expect(demo).not.toContain("Validación formal")
  })
})

describe("cobertura por grado (§0-20): la tabla sola escondería media cartera", () => {
  const conGrados = (
    porGrado: ValidationCalibrationRow[],
    noEvaluados: ValidationNotEvaluableGrade[],
  ): ResultsResponse => ({
    ...(demoF1 as unknown as ResultsResponse),
    validation: {
      ...VALIDATION_F1,
      calibration: [...(VALIDATION_F1.calibration ?? []), ...porGrado],
      metric_sections: {
        validation: {
          ...VALIDATION_F1.metric_sections?.validation,
          not_evaluable_grades: noEvaluados,
        },
      },
    },
  })

  const gradoEvaluado: ValidationCalibrationRow = {
    partition: "desarrollo",
    test: "jeffreys",
    grade: "A",
    n: 500,
    observed_defaults: 40,
    expected_pd: 0.08,
    observed_dr: 0.08,
    statistic: 0.1,
    degrees_of_freedom: null,
    p_value: 0.91,
    alpha: 0.05,
    decision: "pass",
    traffic_light: "green",
  }
  const gradoBajoMinimo: ValidationNotEvaluableGrade = {
    grade: "Z",
    n: 12,
    observed_defaults: 3,
    expected_pd: 0.2,
    observed_dr: 0.25,
    min_rows: 30,
    status: "not_evaluable",
  }

  it("con cobertura parcial declara cuántos grados se evaluaron y enumera los que no", () => {
    const html = render(conGrados([gradoEvaluado], [gradoBajoMinimo]))
    expect(html).toContain("1 de 2 evaluados")
    expect(html).toContain("Grados no evaluados (1)")
    // Las cinco columnas que D-SC-9 exige, más el mínimo que lo dejó fuera.
    expect(html).toContain("Z")
    expect(html).toContain("Mínimo")
    expect(html).toContain("no recibe semáforo ni cuenta en las pruebas")
    // 🔴 Y el estado del motor NO se recalcula por tener un grado fuera.
    expect(html).toContain("1 de 3")
  })

  it("con TODOS los grados bajo el mínimo, cero evaluados y ningún semáforo", () => {
    const html = render(conGrados([], [gradoBajoMinimo]))
    expect(html).toContain("0 de 1 evaluados")
    expect(html).toContain("Grados no evaluados (1)")
    expect(html).not.toContain("Verde")
    expect(html).not.toContain("Ámbar")
    expect(html).not.toContain("Rojo")
  })

  it("sin contraste por grado no se pinta la sección de cobertura", () => {
    const html = render(conGrados([], []))
    expect(html).not.toContain("evaluados")
    expect(html).not.toContain("Grados no evaluados")
  })
})

describe("«Análisis exploratorio» (D-SC-5): los tres casos de la card, con sus rótulos", () => {
  const TITULO_EDA = "Análisis exploratorio"
  const conEda = (eda: EdaResult | null): ResultsResponse => ({ ...minima(null), eda })
  const base = EDA_SCORECARD_REAL

  it("cohorte inferida: barras, no línea, y la nota de que el eje salió de la partición", () => {
    // La corrida real: config `period` sin fecha → el motor tomó la cohorte (D-SC-3).
    expect(base.axis).toBe("cohort")
    expect(base.axis_inferred).toBe(true)
    const html = render(conEda(base))
    expect(ocurrencias(html, TITULO_EDA)).toBe(1)
    expect(html).toContain('data-eda-chart="bar"')
    expect(html).not.toContain('data-eda-chart="line"')
    expect(html).toContain("Eje tomado de la partición por cohorte")
    expect(html).toContain("Agrupada por cohorte")
    expect(html).toContain("5 cohortes")
    // La señal temporal no se evalúa sobre cohortes, y se dice con su causa, sin inventar valor.
    expect(html).toContain("No evaluable: eje de cohorte, sin orden cronológico")
    expect(html).not.toContain("NaN")
  })

  it("🔴 control negativo del §6: la figura se decide por el eje EFECTIVO, no por el del config", () => {
    // Misma corrida, misma card, pero con el eje efectivo `period` y dos períodos: línea. Si el
    // panel decidiera por el config —que dice `period` en los dos casos— pintaría una línea sobre
    // las cohortes de arriba, y este par de aserciones lo delataría.
    const html = render(conEda({ ...base, axis: "period", axis_inferred: false }))
    expect(html).toContain('data-eda-chart="line"')
    expect(html).not.toContain("Eje tomado de la partición por cohorte")
    expect(html).toContain("Agrupada por fecha de observación")
    expect(html).toContain("5 períodos")
  })

  it("período único: sin figura de un punto, y se dice", () => {
    const unPeriodo: EdaResult = {
      ...base,
      axis: "period",
      axis_inferred: false,
      n_periods: 1,
      default_rate: base.default_rate?.slice(0, 1) ?? null,
      stability_not_evaluable_reason: "pocos_periodos_evaluables",
    }
    const html = render(conEda(unPeriodo))
    expect(html).not.toContain("data-eda-chart")
    expect(html).toContain("Un solo período con observaciones: la tasa en el tiempo no se grafica")
    expect(html).toContain("1 período")
    expect(html).toContain(
      "No evaluable: menos de dos períodos con observaciones suficientes",
    )
  })

  it("varios períodos con menos de dos suficientes: misma causa, y las filas poco fiables marcadas", () => {
    const filas = (base.default_rate ?? []).map((row, i) => ({ ...row, low_confidence: i > 0 }))
    const html = render(
      conEda({
        ...base,
        axis: "period",
        axis_inferred: false,
        default_rate: filas,
        stability_not_evaluable_reason: "pocos_periodos_evaluables",
      }),
    )
    expect(html).toContain("No evaluable: menos de dos períodos con observaciones suficientes")
    expect(ocurrencias(html, "Poco fiable: bajo el mínimo")).toBe(filas.length - 1)
    expect(ocurrencias(html, ">Suficiente<")).toBe(1)
  })

  it("dos períodos suficientes sin incumplimientos: causa «tasa media cero» con un indicador relativo", () => {
    const html = render(
      conEda({
        ...base,
        axis: "period",
        axis_inferred: false,
        n_periods: 2,
        stability_metric_used: "cv",
        stability_value: null,
        stability_not_evaluable_reason: "tasa_media_cero",
      }),
    )
    expect(html).toContain("No evaluable: sin incumplimientos en los períodos evaluables")
    expect(html).toContain("El indicador configurado es variación relativa")
  })

  it("con la pendiente el mismo caso es evaluable: valor cero, sin causa y sin aviso", () => {
    const html = render(
      conEda({
        ...base,
        axis: "period",
        axis_inferred: false,
        stability_metric_used: "trend_slope",
        stability_value: 0,
        stability_not_evaluable_reason: null,
      }),
    )
    expect(html).toContain("Sin aviso: tendencia")
    expect(html).not.toContain("No evaluable")
  })

  it("una señal marcada dice que es un aviso de exploración y publica valor y umbral", () => {
    const html = render(
      conEda({
        ...base,
        axis: "period",
        axis_inferred: false,
        stability_flagged: true,
        stability_metric_used: "max_relative_drift",
        stability_value: 0.41,
        stability_threshold: 0.25,
        stability_not_evaluable_reason: null,
      }),
    )
    expect(html).toContain("Aviso de posible redesarrollo: peor desvío")
    expect(html).toContain("0.4100")
    expect(html).toContain("0.2500")
  })

  it("las marcas de calidad salen en palabras y las columnas descritas en su desplegable", () => {
    const html = render(conEda(base))
    expect(html).toContain("casi constante")
    expect(html).toContain("casi única")
    expect(html).not.toContain("near_constant")
    expect(html).not.toContain("near_unique")
    expect(html).not.toContain("high_cardinality")
    for (const columna of new Set((base.univariate ?? []).map((r) => r.column))) {
      expect(html).toContain(columna)
    }
    // Las columnas que definen el target y la cohorte-eje no se describieron (§8-8, D-SC-3).
    expect((base.univariate ?? []).some((r) => r.column === "bad_flag")).toBe(false)
    expect((base.univariate ?? []).some((r) => r.column === "cohorte")).toBe(false)
  })

  it("ningún slug del motor llega a la pantalla", () => {
    const html = render(conEda(base))
    for (const slug of ["eje_cohorte", "pocos_periodos_evaluables", "tasa_media_cero", ">cv<"]) {
      expect(html, slug).not.toContain(slug)
    }
  })

  it("va primero entre los analíticos: antes de «Discriminación»", () => {
    const f1 = demoF1 as unknown as ResultsResponse
    const html = render({ ...f1, eda: base })
    const posEda = html.indexOf(TITULO_EDA)
    const posDiscriminacion = html.indexOf(">Discriminación<")
    expect(posEda).toBeGreaterThan(-1)
    expect(posDiscriminacion).toBeGreaterThan(posEda)
  })

  it("sin `eda` el bloque entero desaparece, ni vacío ni fabricado", () => {
    for (const eda of [null, undefined]) {
      const html = render({ ...minima(null), eda })
      expect(html).not.toContain(TITULO_EDA)
      expect(html).not.toContain("data-eda-chart")
    }
    // Las corridas de la demo se capturaron antes de esta clave y siguen renderizando.
    for (const [nombre, demo] of DEMOS) {
      expect(render(demo), nombre).not.toContain(TITULO_EDA)
    }
  })
})
