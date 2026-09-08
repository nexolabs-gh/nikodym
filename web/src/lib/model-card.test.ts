/**
 * La proyección de la ficha del modelo (D-GOB-15) sobre la ficha REAL de una corrida con
 * gobernanza (`model-card.fixture.ts`, corrida `4b04cbde…` del preset F1). Lo que se prueba aquí es
 * la lógica pura que la pantalla consume; que la sección de verdad se monte con card y no sin ella
 * vive en `components/ResultsTab.test.ts`, y el tipo contra el serializador Python en
 * `tests/unit/test_gobernanza_en_pantalla.py`.
 */

import { describe, expect, it } from "vitest"

import { MODEL_CARD_F1 } from "@/lib/model-card.fixture"
import {
  MODEL_CARD_NO_PINTADO,
  describeValue,
  flattenEvidence,
  isoDate,
  modelCardDecisionRows,
  modelCardDomains,
  modelCardTieneAvisosDeclarados,
} from "@/lib/model-card"
import type { ModelCard, ModelCardDecision } from "@/lib/results-types"

/**
 * La decisión REAL con la que el motor interno de provisiones deja escrita una imputación: con
 * `fail_on_falta_dato=false`, un dato numérico ausente se imputa a cero y `internal_falta_dato`
 * lleva el código de la institución en `valor` (`step.py`, `engine.py::_required_decimal`). Lo
 * señaló la revisión adversarial de S4: la ficha no puede publicarlo mudo.
 */
const IMPUTACION: ModelCardDecision = {
  step: null,
  regla: "internal_falta_dato",
  umbral: false,
  valor: { falta_dato: ["DATO-INSTITUCIONAL"], warning_codes: ["DATO-INSTITUCIONAL"] },
  accion: "trazar_faltantes_y_avisos",
  ts: "2026-09-08T03:27:35.000000Z",
}

describe("todo campo de la ficha está PINTADO o declarado como no pintado, con su razón", () => {
  // Mismo gate que la procedencia (D-LIN-1): el payload publica la ficha entera y la pantalla
  // enseña menos. Sin esto «el panel pinta la ficha» es una sobrepromesa y la sección puede
  // encogerse campo a campo sin que nada lo note. El oráculo se deriva de las claves de la ficha
  // real, nunca de una lista escrita al lado.
  const delCard = Object.keys(MODEL_CARD_F1)
  // Lo que `ModelCardSection` pinta directo (propósito, listas, fechas y conteo)…
  const pintadoDirecto = [
    "purpose",
    "assumptions",
    "limitations",
    "review_date",
    "next_review_date",
    "decisions",
  ]
  // …y lo que pinta a través de la proyección por dominio.
  const pintadoCompuesto = ["metrics", "metric_sections"]

  it("ninguna clave queda sin clasificar", () => {
    const sinClasificar = delCard.filter(
      (campo) =>
        !pintadoDirecto.includes(campo) &&
        !pintadoCompuesto.includes(campo) &&
        !(campo in MODEL_CARD_NO_PINTADO),
    )
    expect(sinClasificar).toEqual([])
  })

  it("no se declara como no pintada una clave que la ficha no trae, ni una que sí se pinta", () => {
    for (const campo of Object.keys(MODEL_CARD_NO_PINTADO)) {
      expect(delCard, campo).toContain(campo)
      expect([...pintadoDirecto, ...pintadoCompuesto], campo).not.toContain(campo)
    }
  })

  it("cada razón de no-pintado explica algo, no es un hueco", () => {
    for (const [campo, razon] of Object.entries(MODEL_CARD_NO_PINTADO)) {
      expect(razon.length, campo).toBeGreaterThan(20)
    }
  })

  it("la ficha real trae las 19 claves que el serializador emite hoy", () => {
    // Ancla contra la medición de la enmienda (§3 D-GOB-16: «19 claves, medidas sobre la
    // respuesta real»). Si el serializador ganara o perdiera una, primero se rompe el gate Python
    // de espejo; este número evita que el fixture se recorte en silencio.
    expect(delCard).toHaveLength(19)
  })
})

describe("isoDate", () => {
  it("deja la fecha calendario de una marca ISO en UTC", () => {
    expect(isoDate("2026-09-03T01:06:03.859794Z")).toBe("2026-09-03")
    expect(isoDate("2027-09-03T01:06:03.859794Z")).toBe("2027-09-03")
  })

  it("no adivina sobre una marca sin esa forma", () => {
    expect(isoDate("ayer")).toBe("ayer")
    expect(isoDate("")).toBe("")
  })
})

describe("describeValue: describe sin interpretar", () => {
  it("escalares", () => {
    expect(describeValue("cohort")).toBe("cohort")
    expect(describeValue(6)).toBe("6")
    expect(describeValue(3961)).toBe("3,961")
    expect(describeValue(0.02)).toBe("0.0200")
    expect(describeValue(true)).toBe("Sí")
    expect(describeValue(false)).toBe("No")
  })

  it("un número diminuto no colapsa a cero: una tolerancia de 1e-8 se lee como tal", () => {
    expect(describeValue(1e-8)).toBe("1.0e-8")
    expect(describeValue(0)).toBe("0")
  })

  it("lo vacío se marca ausente, no se omite", () => {
    expect(describeValue(null)).toBe("—")
    expect(describeValue(undefined)).toBe("—")
    expect(describeValue("")).toBe("—")
    expect(describeValue([])).toBe("—")
    expect(describeValue({})).toBe("—")
  })

  it("listas y objetos en una línea; lo anidado más hondo en JSON", () => {
    expect(describeValue(["binning", "selection"])).toBe("binning, selection")
    expect(describeValue({ n_bins: 5, variable: "utilizacion_linea" })).toBe(
      "n_bins: 5 · variable: utilizacion_linea",
    )
    expect(describeValue({ sizes: { desarrollo: 3961 }, ok: true })).toBe(
      'sizes: {"desarrollo":3961} · ok: Sí',
    )
    expect(describeValue([{ feature: "a", woe: 0 }])).toBe('{"feature":"a","woe":0}')
  })

  it("una lista de escalares dentro de un objeto se lee con comas, no como JSON", () => {
    // Es la forma de `internal_falta_dato.valor`: los códigos tienen que leerse tal cual.
    expect(describeValue({ falta_dato: ["A", "B"], n: 1 })).toBe("falta_dato: A, B · n: 1")
    // …pero una lista de objetos dentro de un objeto sigue en JSON: no hay forma plana honesta.
    expect(describeValue({ filas: [{ a: 1 }] })).toBe('filas: [{"a":1}]')
  })
})

describe("flattenEvidence: el payload CT-2 de un dominio a filas etiqueta → valor", () => {
  it("una subsección con entradas da una fila por entrada, rotulada subsección · clave", () => {
    expect(flattenEvidence(MODEL_CARD_F1.metric_sections.performance)).toEqual([
      {
        label: "discrimination · effective_deciles_by_partition",
        value: "desarrollo: 10 · holdout: 10 · oot: 10",
        avisoDeclarado: false,
      },
      {
        label: "discrimination · not_evaluable_reasons_by_partition",
        value: "—",
        avisoDeclarado: false,
      },
      {
        label: "discrimination · threshold_flags_by_partition",
        value: "—",
        avisoDeclarado: false,
      },
    ])
  })

  it("una subsección escalar o vacía da una sola fila", () => {
    expect(flattenEvidence({ eje: "period", vacia: {}, lista: [1, 2] })).toEqual([
      { label: "eje", value: "period", avisoDeclarado: false },
      { label: "vacia", value: "—", avisoDeclarado: false },
      { label: "lista", value: "1, 2", avisoDeclarado: false },
    ])
  })

  it("la evidencia CT-2 que trae warning_codes queda marcada como aviso declarado", () => {
    // El motor interno de provisiones publica sus `warning_codes` en su sección CT-2.
    expect(
      flattenEvidence({
        provisioning_internal: { warning_codes: ["DATO-INSTITUCIONAL"], n_groups: 3 },
      }),
    ).toEqual([
      {
        label: "provisioning_internal · warning_codes",
        value: "DATO-INSTITUCIONAL",
        avisoDeclarado: true,
      },
      { label: "provisioning_internal · n_groups", value: "3", avisoDeclarado: false },
    ])
  })
})

describe("modelCardDomains: las métricas agrupadas por dominio, en el orden de la ficha", () => {
  const dominios = modelCardDomains(MODEL_CARD_F1)

  it("un dominio por prefijo, en el orden en que el pipeline los publicó", () => {
    expect(dominios.map((d) => d.domain)).toEqual([
      "data",
      "binning",
      "selection",
      "model",
      "scorecard",
      "calibration",
      "performance",
      "stability",
    ])
  })

  it("el rótulo es el de la sección del formulario, no la clave", () => {
    const rotulos = Object.fromEntries(dominios.map((d) => [d.domain, d.label]))
    expect(rotulos.performance).toBe("Performance")
    expect(rotulos.stability).toBe("Estabilidad")
    expect(rotulos.calibration).toBe("Calibración")
    expect(rotulos.data).not.toBe("data")
  })

  it("cada métrica pierde el prefijo y se formatea: conteos con miles, el resto a 4 decimales", () => {
    const data = dominios.find((d) => d.domain === "data")
    expect(data?.metrics).toEqual([
      { name: "n_rows", value: "6,000" },
      { name: "n_features", value: "8" },
      { name: "bad_rate", value: "0.2345" },
    ])
    const performance = dominios.find((d) => d.domain === "performance")
    expect(performance?.metrics).toHaveLength(9)
    expect(performance?.metrics[0]).toEqual({ name: "auc_desarrollo", value: "0.7123" })
  })

  it("la evidencia estructurada (CT-2) cuelga de su dominio y los demás quedan sin ella", () => {
    const stability = dominios.find((d) => d.domain === "stability")
    expect(stability?.evidence).toEqual([
      { label: "stability · temporal_axis", value: "period", avisoDeclarado: false },
      { label: "stability · include_pd_stability", value: "Sí", avisoDeclarado: false },
      {
        label: "stability · csi_features",
        value:
          "antiguedad_meses__points, deuda_ingreso__points, ingreso_mensual__points, " +
          "mora_max_12m__points, utilizacion_linea__points",
        avisoDeclarado: false,
      },
      { label: "stability · n_periods", value: "6", avisoDeclarado: false },
    ])
    expect(dominios.find((d) => d.domain === "data")?.evidence).toEqual([])
  })

  it("un dominio que sólo aporta evidencia estructurada va al final, sin métricas", () => {
    const card: ModelCard = {
      ...MODEL_CARD_F1,
      metrics: { "performance.auc_oot": 0.5 },
      metric_sections: { survival: { curva: { n_periodos: 12 } } },
    }
    expect(modelCardDomains(card)).toEqual([
      {
        domain: "performance",
        label: "Performance",
        metrics: [{ name: "auc_oot", value: "0.5000" }],
        evidence: [],
      },
      {
        domain: "survival",
        label: "Survival — PD lifetime",
        metrics: [],
        evidence: [{ label: "curva · n_periodos", value: "12", avisoDeclarado: false }],
      },
    ])
  })

  it("una métrica sin prefijo no se oculta, y un dominio sin sección cae a su clave", () => {
    const card: ModelCard = {
      ...MODEL_CARD_F1,
      metrics: { suelta: 1, "externo.x": 2 },
      metric_sections: {},
    }
    expect(modelCardDomains(card).map((d) => [d.domain, d.label])).toEqual([
      ["", "otras"],
      ["externo", "externo"],
    ])
  })

  it("sin métricas ni evidencia no hay dominios: la sección no fabrica un resumen vacío", () => {
    expect(modelCardDomains({ ...MODEL_CARD_F1, metrics: {}, metric_sections: {} })).toEqual([])
  })
})

describe("modelCardDecisionRows: una fila por evento del trail, sin agrupar", () => {
  const filas = modelCardDecisionRows(MODEL_CARD_F1)

  it("el conteo que la ficha titula es el largo de la lista", () => {
    expect(filas).toHaveLength(MODEL_CARD_F1.decisions.length)
    expect(filas).toHaveLength(8)
  })

  it("umbral y valor se describen según su tipo real, no se interpretan", () => {
    const por = (regla: string) => filas.find((f) => f.regla === regla)
    expect(por("partition_strategy")).toEqual({
      ts: "2026-09-03T01:05:41.512580Z",
      step: null,
      regla: "partition_strategy",
      accion: "aplicar_estrategia",
      umbral: "cohort",
      valor: "cohort",
      avisoDeclarado: false,
    })
    expect(por("bins_colapsados")?.umbral).toBe("6")
    expect(por("bins_colapsados")?.valor).toBe("n_bins: 5 · variable: utilizacion_linea")
    expect(por("iv_bajo")?.umbral).toBe("0.0200")
    expect(por("statsmodels_convergence")?.umbral).toBe("fit_maxiter: 100 · tol: 1.0e-8")
    expect(por("statsmodels_convergence")?.valor).toBe(
      "converged: Sí · n_iterations: 6 · optimizer: newton",
    )
    expect(por("report_sections")?.umbral).toBe(
      "binning, selection, model, scorecard, calibration, performance, stability",
    )
    expect(por("report_ai_disabled")?.umbral).toBe("No")
    expect(por("woe_duplicado")?.valor).toContain('"feature":"antiguedad_meses"')
  })

  it("el paso se conserva cuando el evento lo trae", () => {
    const card: ModelCard = {
      ...MODEL_CARD_F1,
      decisions: [{ ...MODEL_CARD_F1.decisions[0], step: "selection" }],
    }
    expect(modelCardDecisionRows(card)[0].step).toBe("selection")
  })
})

describe("avisos declarados en lo que la ficha pinta (revisión adversarial de S4)", () => {
  it("la decisión que registra la imputación queda marcada, con su código intacto; las demás no", () => {
    const filas = modelCardDecisionRows({
      ...MODEL_CARD_F1,
      decisions: [...MODEL_CARD_F1.decisions, IMPUTACION],
    })
    expect(filas.at(-1)).toMatchObject({
      regla: "internal_falta_dato",
      umbral: "No",
      valor: "falta_dato: DATO-INSTITUCIONAL · warning_codes: DATO-INSTITUCIONAL",
      avisoDeclarado: true,
    })
    expect(filas.slice(0, -1).every((f) => !f.avisoDeclarado)).toBe(true)
  })

  it("la marca reconoce las dos familias, también con sufijo, y en el umbral", () => {
    const filas = modelCardDecisionRows({
      ...MODEL_CARD_F1,
      decisions: [
        { ...IMPUTACION, umbral: "FALTA-DATO-PROV-9", valor: "x" },
        { ...IMPUTACION, umbral: "x", valor: ["DATO-INSTITUCIONAL-IFRS-7"] },
        { ...IMPUTACION, umbral: "x", valor: "sin marca" },
      ],
    })
    expect(filas.map((f) => f.avisoDeclarado)).toEqual([true, true, false])
  })

  it("la ficha F1 real no lleva ninguno: la sección no explica una salvedad que no ocurrió", () => {
    expect(
      modelCardTieneAvisosDeclarados(
        modelCardDomains(MODEL_CARD_F1),
        modelCardDecisionRows(MODEL_CARD_F1),
      ),
    ).toBe(false)
  })

  it("basta un aviso en una decisión o en la evidencia CT-2 para que la sección lo explique", () => {
    const conDecision: ModelCard = { ...MODEL_CARD_F1, decisions: [IMPUTACION] }
    expect(
      modelCardTieneAvisosDeclarados(
        modelCardDomains(conDecision),
        modelCardDecisionRows(conDecision),
      ),
    ).toBe(true)
    const conEvidencia: ModelCard = {
      ...MODEL_CARD_F1,
      metric_sections: {
        provisioning_internal: { provisioning_internal: { warning_codes: ["FALTA-DATO-PROV-9"] } },
      },
    }
    expect(
      modelCardTieneAvisosDeclarados(
        modelCardDomains(conEvidencia),
        modelCardDecisionRows(conEvidencia),
      ),
    ).toBe(true)
  })
})
