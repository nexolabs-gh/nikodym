import { describe, expect, it } from "vitest"

import {
  EMPTY,
  bandsPresent,
  comparisonLabel,
  csiBars,
  discriminantRows,
  formatBool,
  formatCount,
  formatMetric,
  formatPValue,
  formatPercent,
  gainsSeries,
  liftByDecile,
  partitionLabel,
  primaryPartition,
  psiBars,
  scoreHistogram,
  sortByIv,
  temporalScore,
} from "./results-format"
import type {
  DecileRow,
  ResultsResponse,
  StabilityMetricRow,
} from "./results-types"

/**
 * Fixture tipado con VALORES REALES del preset estándar (recorte de `results_real.json`,
 * B27). Que este objeto compile como `ResultsResponse` YA es una verificación del contrato:
 * si los DTOs no reflejaran el shape real, `tsc` fallaría aquí. Sobre él se ejercitan los
 * helpers, que es lo que consume la pestaña Resultados.
 */
const sample: ResultsResponse = {
  status: "done",
  run_id: "efa02b4dd34f4f9a943ed6a07297f372",
  error: null,
  model_card: null,
  binning: {
    n_variables_requested: 6,
    n_variables_binned: 6,
    n_variables_skipped: 0,
    iv_by_variable: {
      ingreso_mensual: 0.3047503805275573,
      deuda_ingreso: 0.16351868514809573,
      utilizacion_linea: 0.06103129307994183,
      mora_max_12m: 0.02187037115021461,
      antiguedad_meses: 0.04137938933212,
      segmento: 0.002922409359928141,
    },
  },
  model: {
    engine: "statsmodels",
    n_candidates: 6,
    n_final_features: 5,
    final_features: [
      "antiguedad_meses",
      "deuda_ingreso",
      "ingreso_mensual",
      "mora_max_12m",
      "utilizacion_linea",
    ],
    fit_statistics: {
      n_obs_dev: 3961,
      n_events_dev: 924,
      n_nonevents_dev: 3037,
      log_likelihood: -1943.3578672306817,
      null_log_likelihood: -2151.6258790454076,
      pseudo_r2_mcfadden: 0.09679564363072557,
      aic: 3898.7157344613634,
      bic: 3936.4212452470947,
      llr: 416.53602362945185,
      llr_p_value: 8.086740322817964e-88,
      converged: true,
      optimizer: "newton",
      n_iterations: 6,
    },
    coefficients: [
      {
        feature: "intercept",
        woe_column: "const",
        beta: -1.192118528580642,
        standard_error: 0.04052082326442768,
        wald_z: -29.41989901836906,
        p_value: 3.0566632058876624e-190,
        conf_low: -1.271537882802833,
        conf_high: -1.112699174358451,
        expected_sign: "none",
        sign_ok: null,
        iv: null,
        iv_contribution: null,
      },
      {
        feature: "antiguedad_meses",
        woe_column: "antiguedad_meses__woe",
        beta: -1.0810393440369799,
        standard_error: 0.210068811686856,
        wald_z: -5.146120146804355,
        p_value: 2.6592913727782066e-7,
        conf_low: -1.4927666492183445,
        conf_high: -0.6693120388556153,
        expected_sign: "negative",
        sign_ok: true,
        iv: 0.04137938933212,
        iv_contribution: 0.06983272467371615,
      },
    ],
  },
  scorecard: {
    pdo: 20.0,
    target_score: 600,
    target_odds: 50,
    factor: 28.85390081777927,
    offset: 487.1229234749674,
    score_direction: "higher_is_safer",
    rounding_method: "nearest",
    n_variables: 5,
    score_column: "score",
    points_columns: [],
    min_score: null,
    max_score: null,
    overrides_count: 0,
  },
  calibration: {
    method: "intercept_offset",
    target_pd: 0.2,
    anchor_kind: "through_the_cycle",
    anchor_source: "business_input",
    fit_partition: "desarrollo",
    n_fit: 3961,
    raw_mean_pd_dev: 0.23327442565008835,
    calibrated_mean_pd_dev: 0.20000000000000798,
    observed_default_rate_dev: 0.23327442565008835,
    offset: -0.21844701788025583,
    slope: null,
    intercept: null,
    ranking_preserved: true,
    ties_created: 0,
    pd_raw_column: "pd_raw",
    pd_calibrated_column: "pd_calibrated",
    isotonic_knots: null,
  },
  performance: {
    evaluation_source: "pd_calibrated",
    score_direction: "higher_is_safer",
    partitions: ["desarrollo", "holdout", "oot"],
    n_deciles: 10,
    max_metrics_by_partition: {
      desarrollo: {
        auc: 0.7123458941453674,
        gini: 0.42469178829073484,
        ks: 0.32014426688447106,
      },
      holdout: {
        auc: 0.6946460932780636,
        gini: 0.3892921865561272,
        ks: 0.3118920157477034,
      },
      oot: {
        auc: 0.6560957827097084,
        gini: 0.31219156541941673,
        ks: 0.25190569723218226,
      },
    },
    discriminant: [
      {
        partition: "desarrollo",
        n_total: 3961,
        n_bad: 924,
        n_good: 3037,
        auc: 0.7123458941453674,
        gini: 0.42469178829073484,
        ks: 0.32014426688447106,
        ks_cutoff_risk_score: 0.18965137281059444,
        ks_cutoff_score: null,
        tpr_at_ks: 0.7067099567099567,
        fpr_at_ks: 0.38656568982548567,
        source: "pd_calibrated",
        status: "ok",
      },
      {
        partition: "holdout",
        n_total: 1000,
        n_bad: 240,
        n_good: 760,
        auc: 0.6946460932780636,
        gini: 0.3892921865561272,
        ks: 0.3118920157477034,
        ks_cutoff_risk_score: 0.2,
        ks_cutoff_score: null,
        tpr_at_ks: 0.7,
        fpr_at_ks: 0.38,
        source: "pd_calibrated",
        status: "ok",
      },
      {
        partition: "oot",
        n_total: 1200,
        n_bad: 300,
        n_good: 900,
        auc: 0.6560957827097084,
        gini: 0.31219156541941673,
        ks: 0.25190569723218226,
        ks_cutoff_risk_score: 0.21,
        ks_cutoff_score: null,
        tpr_at_ks: 0.65,
        fpr_at_ks: 0.4,
        source: "pd_calibrated",
        status: "ok",
      },
    ],
  },
}

describe("formatMetric", () => {
  it("formatea a 4 decimales por defecto (AUC/Gini/KS)", () => {
    expect(formatMetric(0.7123458941453674)).toBe("0.7123")
  })

  it("respeta el número de decimales pedido", () => {
    expect(formatMetric(0.42469178829073484, 3)).toBe("0.425")
  })

  it("devuelve EMPTY para null/undefined/no finito", () => {
    expect(formatMetric(null)).toBe(EMPTY)
    expect(formatMetric(undefined)).toBe(EMPTY)
    expect(formatMetric(Number.NaN)).toBe(EMPTY)
    expect(formatMetric(Number.POSITIVE_INFINITY)).toBe(EMPTY)
  })
})

describe("formatPValue", () => {
  it("usa notación exponencial para p-values diminutos", () => {
    expect(formatPValue(8.086740322817964e-88)).toBe("8.1e-88")
    expect(formatPValue(3.0566632058876624e-190)).toBe("3.1e-190")
  })

  it("usa 4 decimales para p-values normales", () => {
    expect(formatPValue(0.0342)).toBe("0.0342")
    expect(formatPValue(0)).toBe("0.0000")
  })

  it("devuelve EMPTY para ausente/no finito", () => {
    expect(formatPValue(null)).toBe(EMPTY)
    expect(formatPValue(undefined)).toBe(EMPTY)
  })
})

describe("formatPercent", () => {
  it("convierte proporción a porcentaje (1 decimal por defecto)", () => {
    expect(formatPercent(0.2)).toBe("20.0%")
    expect(formatPercent(0.23327442565008835, 2)).toBe("23.33%")
  })

  it("devuelve EMPTY para ausente/no finito", () => {
    expect(formatPercent(null)).toBe(EMPTY)
  })
})

describe("formatCount", () => {
  it("agrupa miles con coma inequívoca (determinista, sin ICU)", () => {
    expect(formatCount(3961)).toBe("3,961")
    expect(formatCount(1234567)).toBe("1,234,567")
    expect(formatCount(0)).toBe("0")
    expect(formatCount(924)).toBe("924")
  })

  it("devuelve EMPTY para ausente/no finito", () => {
    expect(formatCount(null)).toBe(EMPTY)
    expect(formatCount(undefined)).toBe(EMPTY)
  })
})

describe("formatBool", () => {
  it("mapea booleanos a Sí/No y ausente a EMPTY", () => {
    expect(formatBool(true)).toBe("Sí")
    expect(formatBool(false)).toBe("No")
    expect(formatBool(null)).toBe(EMPTY)
    expect(formatBool(undefined)).toBe(EMPTY)
  })
})

describe("discriminantRows", () => {
  it("deriva una fila por partición desde `discriminant` (rico)", () => {
    const rows = discriminantRows(sample.performance)
    expect(rows).toHaveLength(3)
    expect(rows.map((r) => r.partition)).toEqual([
      "desarrollo",
      "holdout",
      "oot",
    ])
    expect(rows[0]).toEqual({
      partition: "desarrollo",
      auc: 0.7123458941453674,
      gini: 0.42469178829073484,
      ks: 0.32014426688447106,
    })
  })

  it("cae a `max_metrics_by_partition` respetando el orden de `partitions`", () => {
    const rows = discriminantRows({
      ...sample.performance!,
      discriminant: [],
    })
    expect(rows.map((r) => r.partition)).toEqual([
      "desarrollo",
      "holdout",
      "oot",
    ])
    expect(rows[2].ks).toBe(0.25190569723218226)
  })

  it("devuelve [] cuando falta performance (corrida parcial)", () => {
    expect(discriminantRows(undefined)).toEqual([])
  })
})

describe("sortByIv", () => {
  it("ordena feature→IV de mayor a menor", () => {
    const rows = sortByIv(sample.binning?.iv_by_variable)
    expect(rows.map((r) => r.feature)).toEqual([
      "ingreso_mensual",
      "deuda_ingreso",
      "utilizacion_linea",
      "antiguedad_meses",
      "mora_max_12m",
      "segmento",
    ])
    expect(rows[0].iv).toBeCloseTo(0.30475, 5)
  })

  it("devuelve [] cuando falta el mapa de IV", () => {
    expect(sortByIv(undefined)).toEqual([])
  })
})

describe("resiliencia a corrida failed/parcial", () => {
  it("los helpers no rompen con un payload sin secciones de dominio", () => {
    const failed: ResultsResponse = {
      status: "failed",
      run_id: "abc",
      error: "algo salió mal",
      model_card: null,
    }
    expect(discriminantRows(failed.performance)).toEqual([])
    expect(sortByIv(failed.binning?.iv_by_variable)).toEqual([])
    // Helpers de estabilidad: robustos a `stability` ausente/`null`.
    expect(psiBars(failed.stability?.stability_metrics, "score_psi")).toEqual([])
    expect(csiBars(failed.stability?.stability_metrics)).toEqual([])
    expect(temporalScore(failed.stability?.stability_metrics)).toBeNull()
  })
})

/**
 * Filas de `stability_metrics` con VALORES REALES del preset (PSI del score/PD ≈ 0.01,
 * todo en banda `stable`) más filas sintéticas de otras bandas/comparaciones para probar
 * el orden y el manejo de todos los enums (no solo el caso "todo verde").
 */
const stabilityMetrics: StabilityMetricRow[] = [
  {
    metric: "score_psi",
    comparison: "dev_vs_oot",
    feature: "score",
    value: 0.0198,
    stable_threshold: 0.1,
    review_threshold: 0.25,
    band: "stable",
    action: "none",
  },
  {
    metric: "score_psi",
    comparison: "dev_vs_holdout",
    feature: "score",
    value: 0.0127,
    stable_threshold: 0.1,
    review_threshold: 0.25,
    band: "stable",
    action: "none",
  },
  {
    metric: "pd_psi",
    comparison: "dev_vs_holdout",
    feature: "pd_calibrated",
    value: 0.0132,
    stable_threshold: 0.1,
    review_threshold: 0.25,
    band: "stable",
    action: "none",
  },
  {
    metric: "csi",
    comparison: "dev_vs_oot",
    feature: "ingreso_mensual",
    value: 0.31,
    stable_threshold: 0.1,
    review_threshold: 0.25,
    band: "redevelop",
    action: "redesarrollar",
  },
  {
    metric: "csi",
    comparison: "dev_vs_oot",
    feature: "deuda_ingreso",
    value: 0.12,
    stable_threshold: 0.1,
    review_threshold: 0.25,
    band: "review",
    action: "vigilar",
  },
  {
    metric: "csi",
    comparison: "dev_vs_oot",
    feature: "segmento",
    value: null,
    stable_threshold: 0.1,
    review_threshold: 0.25,
    band: "not_evaluable",
    action: "none",
  },
  {
    metric: "temporal_score",
    comparison: "period",
    feature: "score",
    value: 0.04,
    stable_threshold: 0.1,
    review_threshold: 0.25,
    band: "stable",
    action: "none",
  },
]

describe("comparisonLabel", () => {
  it("etiqueta las comparaciones conocidas", () => {
    expect(comparisonLabel("dev_vs_holdout")).toBe("Dev vs Holdout")
    expect(comparisonLabel("dev_vs_oot")).toBe("Dev vs OOT")
    expect(comparisonLabel("period")).toBe("Temporal")
  })

  it("cae al propio slug para comparaciones no previstas", () => {
    expect(comparisonLabel("dev_vs_2025q1")).toBe("dev_vs_2025q1")
  })
})

describe("psiBars", () => {
  it("filtra por métrica y ordena por comparación canónica (holdout antes que oot)", () => {
    const rows = psiBars(stabilityMetrics, "score_psi")
    expect(rows.map((r) => r.comparison)).toEqual([
      "dev_vs_holdout",
      "dev_vs_oot",
    ])
    expect(rows[0]).toEqual({
      comparison: "dev_vs_holdout",
      label: "Dev vs Holdout",
      value: 0.0127,
      band: "stable",
    })
  })

  it("aísla la PD calibrada de la del score", () => {
    const rows = psiBars(stabilityMetrics, "pd_psi")
    expect(rows).toHaveLength(1)
    expect(rows[0].value).toBe(0.0132)
  })

  it("devuelve [] cuando falta el frame de métricas", () => {
    expect(psiBars(null, "score_psi")).toEqual([])
    expect(psiBars(undefined, "pd_psi")).toEqual([])
  })
})

describe("csiBars", () => {
  it("ordena por CSI desc y deja los nulos al final", () => {
    const rows = csiBars(stabilityMetrics)
    expect(rows.map((r) => r.feature)).toEqual([
      "ingreso_mensual",
      "deuda_ingreso",
      "segmento",
    ])
    expect(rows[0].band).toBe("redevelop")
    expect(rows[2].value).toBeNull()
  })

  it("devuelve [] cuando falta el frame de métricas", () => {
    expect(csiBars(undefined)).toEqual([])
  })
})

describe("temporalScore", () => {
  it("extrae el escalar temporal cuando está presente", () => {
    expect(temporalScore(stabilityMetrics)).toEqual({
      value: 0.04,
      band: "stable",
    })
  })

  it("devuelve null si no hay fila temporal", () => {
    const sinTemporal = stabilityMetrics.filter(
      (r) => r.metric !== "temporal_score",
    )
    expect(temporalScore(sinTemporal)).toBeNull()
    expect(temporalScore(null)).toBeNull()
  })
})

describe("bandsPresent", () => {
  it("incluye las tres bandas primarias y not_evaluable solo si aparece", () => {
    expect(bandsPresent(stabilityMetrics)).toEqual([
      "stable",
      "review",
      "redevelop",
      "not_evaluable",
    ])
  })

  it("omite not_evaluable cuando no está en los datos (caso todo estable)", () => {
    const soloEstable = stabilityMetrics.filter((r) => r.band === "stable")
    expect(bandsPresent(soloEstable)).toEqual([
      "stable",
      "review",
      "redevelop",
    ])
  })
})

/**
 * Factory de filas de deciles: solo hace falta declarar los campos relevantes del test;
 * el resto toma valores plausibles (invariantes de conteo respetados). Reduce el ruido.
 */
function makeDecile(
  partial: Partial<DecileRow> & { partition: string; decile: number },
): DecileRow {
  return {
    n_total: 100,
    n_bad: 20,
    n_good: 80,
    bad_rate: 0.2,
    good_rate: 0.8,
    mean_pd: 0.2,
    min_pd: 0.1,
    max_pd: 0.3,
    mean_score: 500,
    min_score: 480,
    max_score: 520,
    cum_total: 100,
    cum_bad: 20,
    cum_good: 80,
    cum_bad_capture_rate: 0.5,
    cum_good_capture_rate: 0.5,
    lift: 1,
    ks_at_decile: 0,
    ...partial,
  }
}

/**
 * Deciles de 2 particiones × 3 deciles, con orden deliberadamente barajado (holdout
 * primero, deciles fuera de orden) para verificar que los helpers reordenan.
 */
const deciles: DecileRow[] = [
  makeDecile({ partition: "holdout", decile: 2, cum_bad_capture_rate: 0.65 }),
  makeDecile({ partition: "desarrollo", decile: 3, cum_bad_capture_rate: 1.0, lift: 0.5 }),
  makeDecile({ partition: "holdout", decile: 1, cum_bad_capture_rate: 0.35 }),
  makeDecile({ partition: "desarrollo", decile: 1, cum_bad_capture_rate: 0.4, lift: 2.0 }),
  makeDecile({ partition: "holdout", decile: 3, cum_bad_capture_rate: 1.0 }),
  makeDecile({ partition: "desarrollo", decile: 2, cum_bad_capture_rate: 0.7, lift: 1.5 }),
]

describe("partitionLabel", () => {
  it("etiqueta las particiones conocidas y cae al slug para las demás", () => {
    expect(partitionLabel("desarrollo")).toBe("Desarrollo")
    expect(partitionLabel("holdout")).toBe("Holdout")
    expect(partitionLabel("oot")).toBe("OOT")
    expect(partitionLabel("2025q1")).toBe("2025q1")
  })
})

describe("primaryPartition", () => {
  it("prefiere desarrollo cuando está presente", () => {
    expect(primaryPartition(deciles)).toBe("desarrollo")
  })

  it("cae a la primera partición cuando la preferida no está", () => {
    expect(primaryPartition(deciles, "oot")).toBe("holdout")
  })

  it("devuelve null sin deciles", () => {
    expect(primaryPartition(undefined)).toBeNull()
    expect(primaryPartition([])).toBeNull()
  })
})

describe("gainsSeries", () => {
  it("ordena particiones (canónico) y arma una fila por decil más el origen (0,0)", () => {
    const { partitions, data } = gainsSeries(deciles)
    expect(partitions).toEqual(["desarrollo", "holdout"])
    // 3 deciles + 1 fila ancla de origen.
    expect(data).toHaveLength(4)
    expect(data[0]).toEqual({
      decile: 0,
      random: 0,
      desarrollo: 0,
      holdout: 0,
    })
  })

  it("mapea cum_bad_capture_rate por partición y la diagonal random = k/N", () => {
    const { data } = gainsSeries(deciles)
    // N = 3 (deciles presentes) → decil 1 → 1/3.
    expect(data[1]).toEqual({
      decile: 1,
      random: 1 / 3,
      desarrollo: 0.4,
      holdout: 0.35,
    })
    // Último decil: ganancia 100% y diagonal en 1.0.
    expect(data[3]).toEqual({
      decile: 3,
      random: 1,
      desarrollo: 1.0,
      holdout: 1.0,
    })
  })

  it("pone null en el decil que una partición no tiene (sin fabricar valores)", () => {
    const parcial = [
      makeDecile({ partition: "desarrollo", decile: 1, cum_bad_capture_rate: 0.5 }),
      makeDecile({ partition: "desarrollo", decile: 2, cum_bad_capture_rate: 1.0 }),
      makeDecile({ partition: "oot", decile: 1, cum_bad_capture_rate: 0.3 }),
    ]
    const { partitions, data } = gainsSeries(parcial)
    expect(partitions).toEqual(["desarrollo", "oot"])
    expect(data[2]).toEqual({ decile: 2, random: 1, desarrollo: 1.0, oot: null })
  })

  it("devuelve serie vacía sin deciles", () => {
    expect(gainsSeries(undefined)).toEqual({ partitions: [], data: [] })
    expect(gainsSeries([])).toEqual({ partitions: [], data: [] })
  })
})

describe("liftByDecile", () => {
  it("filtra por partición (default desarrollo) y ordena por decil asc", () => {
    const rows = liftByDecile(deciles)
    expect(rows.map((r) => r.decile)).toEqual([1, 2, 3])
    expect(rows.map((r) => r.lift)).toEqual([2.0, 1.5, 0.5])
  })

  it("respeta la partición pedida y devuelve [] si no está presente", () => {
    expect(liftByDecile(deciles, "holdout").map((r) => r.decile)).toEqual([
      1, 2, 3,
    ])
    expect(liftByDecile(deciles, "oot")).toEqual([])
    expect(liftByDecile(undefined)).toEqual([])
  })
})

describe("scoreHistogram", () => {
  it("agrupa en bins de ancho uniforme y conserva el total", () => {
    const values = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    const h = scoreHistogram(values, 5)
    expect(h).not.toBeNull()
    if (!h) return
    expect(h.bins).toHaveLength(5)
    expect(h.min).toBe(0)
    expect(h.max).toBe(9)
    expect(h.binWidth).toBeCloseTo(1.8, 10)
    // El máximo cae en el último bin (borde derecho = max): no se pierde la cola.
    expect(h.bins[4].x1).toBe(9)
    // Suma de frecuencias == nº de valores finitos (invariante).
    expect(h.bins.reduce((s, b) => s + b.count, 0)).toBe(10)
    expect(h.count).toBe(10)
    // Distribución uniforme → 2 por bin.
    expect(h.bins.map((b) => b.count)).toEqual([2, 2, 2, 2, 2])
    expect(h.mean).toBeCloseTo(4.5, 10)
    expect(h.median).toBeCloseTo(4.5, 10)
  })

  it("usa ~24 bins por defecto", () => {
    const values = Array.from({ length: 101 }, (_, i) => i)
    const h = scoreHistogram(values)
    expect(h?.bins).toHaveLength(24)
  })

  it("mediana impar = valor central", () => {
    const h = scoreHistogram([1, 2, 3, 4, 5], 5)
    expect(h?.median).toBe(3)
  })

  it("ignora valores no finitos y cuenta solo los finitos", () => {
    const h = scoreHistogram([1, 2, Number.NaN, 3, Number.POSITIVE_INFINITY], 3)
    expect(h?.count).toBe(3)
    expect(h?.min).toBe(1)
    expect(h?.max).toBe(3)
  })

  it("caso degenerado (todos iguales): un solo bin de ancho 0", () => {
    const h = scoreHistogram([5, 5, 5], 10)
    expect(h?.binWidth).toBe(0)
    expect(h?.bins).toEqual([{ x0: 5, x1: 5, center: 5, count: 3 }])
    expect(h?.mean).toBe(5)
    expect(h?.median).toBe(5)
  })

  it("devuelve null sin valores finitos o sin datos", () => {
    expect(scoreHistogram(undefined)).toBeNull()
    expect(scoreHistogram([])).toBeNull()
    expect(scoreHistogram([Number.NaN, Number.POSITIVE_INFINITY])).toBeNull()
  })
})
