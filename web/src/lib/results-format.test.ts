import { describe, expect, it } from "vitest"

import {
  EMPTY,
  bandsPresent,
  binnedVariables,
  cmfCategoryBars,
  cmfCategoryLabel,
  comparisonLabel,
  csiBars,
  csiComparisonLabel,
  discriminantRows,
  featureDisplayLabel,
  formatBool,
  formatClp,
  formatClpCompact,
  formatCount,
  formatMetric,
  formatPValue,
  formatPercent,
  formatPercentValue,
  gainsSeries,
  internalGroupBars,
  liftByDecile,
  monotonicityLabel,
  normalizeBinLabel,
  partitionLabel,
  primaryPartition,
  provisioningComparisonBars,
  provisioningHeadline,
  provisioningSourceLabel,
  psiBars,
  reliabilityCurve,
  scoreBandLabel,
  scoreHistogram,
  sortByIv,
  temporalScore,
  variableBinning,
} from "./results-format"
import type {
  BinningResult,
  CalibrationResult,
  CmfProvisioningResult,
  DecileRow,
  InternalProvisioningResult,
  ProvisioningResult,
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
    // Confiabilidad: robusto a `calibration` ausente en una corrida parcial.
    expect(reliabilityCurve(failed.calibration)).toBeNull()
  })
})

/**
 * Filas de `stability_metrics` con VALORES REALES del preset (PSI del score/PD ≈ 0.01,
 * todo en banda `stable`) más filas sintéticas de otras bandas/comparaciones para probar
 * el orden y el manejo de todos los enums (no solo el caso "todo verde").
 */
const csiRow = (
  feature: string,
  comparison: string,
  value: number | null,
  band: StabilityMetricRow["band"],
): StabilityMetricRow => ({
  metric: "csi",
  comparison,
  feature,
  value,
  stable_threshold: 0.1,
  review_threshold: 0.25,
  band,
  action: "none",
})

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

  it("muestra solo la comparación temporal (dev_vs_oot), descarta holdout", () => {
    const mixed: StabilityMetricRow[] = [
      csiRow("ingreso_mensual", "dev_vs_oot", 0.2, "review"),
      csiRow("ingreso_mensual", "dev_vs_holdout", 0.9, "redevelop"),
      csiRow("deuda_ingreso", "dev_vs_oot", 0.05, "stable"),
      csiRow("deuda_ingreso", "dev_vs_holdout", 0.8, "redevelop"),
    ]
    const rows = csiBars(mixed)
    // Una barra por feature (no dos), con los valores de OOT (no los de holdout).
    expect(rows.map((r) => r.feature)).toEqual([
      "ingreso_mensual",
      "deuda_ingreso",
    ])
    expect(rows.map((r) => r.value)).toEqual([0.2, 0.05])
  })

  it("cae a la comparación presente si no hay OOT", () => {
    const soloHoldout = [csiRow("segmento", "dev_vs_holdout", 0.03, "stable")]
    expect(csiBars(soloHoldout).map((r) => r.feature)).toEqual(["segmento"])
  })
})

describe("csiComparisonLabel", () => {
  it("formatea la comparación mostrada (OOT preferida)", () => {
    expect(csiComparisonLabel(stabilityMetrics)).toBe("dev vs OOT")
  })

  it("null cuando no hay CSI", () => {
    expect(csiComparisonLabel(undefined)).toBeNull()
    expect(csiComparisonLabel([])).toBeNull()
  })
})

describe("featureDisplayLabel", () => {
  it("quita el sufijo interno __points de la columna de puntos", () => {
    expect(featureDisplayLabel("ingreso_mensual__points")).toBe(
      "ingreso_mensual",
    )
  })

  it("deja intacto un nombre sin sufijo", () => {
    expect(featureDisplayLabel("deuda_ingreso")).toBe("deuda_ingreso")
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

// --- binning: WoE por bin ---------------------------------------------------

/**
 * Fixture con VALORES REALES del preset (recorte de `results_real.json`, sección binning):
 * una variable numérica (Bin string) con monotonicidad, una categórica (Bin array) sin
 * monotonicidad, filas Special/Missing vacías (Count=0) y la fila Totals (Bin/WoE ""). Que
 * compile como `BinningResult` ya verifica el contrato de tipos del payload.
 */
const binningWithTables: BinningResult = {
  n_variables_requested: 2,
  n_variables_binned: 2,
  n_variables_skipped: 0,
  iv_by_variable: {
    ingreso_mensual: 0.3047503805275573,
    segmento: 0.002922409359928141,
  },
  monotonicity_by_variable: {
    ingreso_mensual: "descending",
    segmento: null,
  },
  tables_by_variable: {
    ingreso_mensual: [
      {
        Bin: "(-inf, 242795.88)",
        Count: 210,
        "Count (%)": 0.053016914920474625,
        "Non-event": 120,
        Event: 90,
        "Event rate": 0.42857142857142855,
        WoE: -0.9022313209522836,
        IV: 0.052230099369214925,
        JS: 0.006315960381075309,
      },
      {
        Bin: "[913196.97, inf)",
        Count: 565,
        "Count (%)": 0.14264074728603887,
        "Non-event": 518,
        Event: 47,
        "Event rate": 0.0831858407079646,
        WoE: 1.2099142471453597,
        IV: 0.14482341390398523,
        JS: 0.01707370995208068,
      },
      {
        Bin: "Special",
        Count: 0,
        "Count (%)": 0,
        "Non-event": 0,
        Event: 0,
        "Event rate": 0,
        WoE: 0,
        IV: 0,
        JS: 0,
      },
      {
        Bin: "Missing",
        Count: 0,
        "Count (%)": 0,
        "Non-event": 0,
        Event: 0,
        "Event rate": 0,
        WoE: 0,
        IV: 0,
        JS: 0,
      },
      {
        Bin: "",
        Count: 3961,
        "Count (%)": 1,
        "Non-event": 3037,
        Event: 924,
        "Event rate": 0.23327442565008835,
        WoE: "",
        IV: 0.3047503805275573,
        JS: 0.03671318287070641,
      },
    ],
    segmento: [
      {
        Bin: ["independiente"],
        Count: 1353,
        "Count (%)": 0.34158040898762937,
        "Non-event": 1052,
        Event: 301,
        "Event rate": 0.22246858832224686,
        WoE: 0.061424735144714804,
        IV: 0.001267615654035145,
        JS: 0.00015842705149731427,
      },
      {
        Bin: ["asalariado"],
        Count: 1303,
        "Count (%)": 0.328957334006564,
        "Non-event": 1001,
        Event: 302,
        "Event rate": 0.23177283192632386,
        WoE: 0.008414368536286299,
        IV: 0.000023238413162702974,
        JS: 0.000002904793075991785,
      },
      {
        Bin: "",
        Count: 3961,
        "Count (%)": 1,
        "Non-event": 3037,
        Event: 924,
        "Event rate": 0.23327442565008835,
        WoE: "",
        IV: 0.002922409359928141,
        JS: 0.0003652349497844324,
      },
    ],
  },
}

describe("normalizeBinLabel", () => {
  it("bin numérico (string) pasa tal cual", () => {
    expect(normalizeBinLabel("[242795.88, 354256.50)")).toBe(
      "[242795.88, 354256.50)",
    )
    expect(normalizeBinLabel("(-inf, 242795.88)")).toBe("(-inf, 242795.88)")
  })

  it("bin categórico (array) se une con ', '", () => {
    expect(normalizeBinLabel(["independiente"])).toBe("independiente")
    expect(normalizeBinLabel(["a", "b"])).toBe("a, b")
    // Categorías numéricas agrupadas → se stringifican.
    expect(normalizeBinLabel([1, 2])).toBe("1, 2")
  })
})

describe("monotonicityLabel", () => {
  it("mapea asc/desc/categórica", () => {
    expect(monotonicityLabel("ascending")).toBe("Monótona ascendente")
    expect(monotonicityLabel("descending")).toBe("Monótona descendente")
    expect(monotonicityLabel(null)).toBe("Categórica")
  })
})

describe("variableBinning", () => {
  it("variable numérica: excluye Totals y bins vacíos, normaliza campos", () => {
    const d = variableBinning(binningWithTables, "ingreso_mensual")
    expect(d).not.toBeNull()
    if (!d) return
    // Solo los 2 bins reales (Special/Missing con Count=0 y Totals fuera).
    expect(d.rows).toHaveLength(2)
    expect(d.rows.map((r) => r.binLabel)).toEqual([
      "(-inf, 242795.88)",
      "[913196.97, inf)",
    ])
    expect(d.rows[0].woe).toBeCloseTo(-0.9022313209522836, 12)
    expect(d.rows[1].woe).toBeCloseTo(1.2099142471453597, 12)
    expect(d.rows[0].eventRate).toBeCloseTo(0.42857142857142855, 12)
    expect(d.rows[0].count).toBe(210)
    // Ninguna fila graficable arrastra el WoE string de Totals.
    expect(d.rows.every((r) => r.woe !== null)).toBe(true)
    expect(d.monotonicity).toBe("descending")
    expect(d.ivTotal).toBeCloseTo(0.3047503805275573, 12)
  })

  it("fila Totals se expone como agregado (pie de tabla), no como bin", () => {
    const d = variableBinning(binningWithTables, "ingreso_mensual")
    expect(d?.total).not.toBeNull()
    expect(d?.total?.totalCount).toBe(3961)
    expect(d?.total?.baseEventRate).toBeCloseTo(0.23327442565008835, 12)
    expect(d?.total?.ivTotal).toBeCloseTo(0.3047503805275573, 12)
    // El WoE "" de Totals no se cuela: el agregado no expone WoE (solo IV/tasa base).
    expect(d?.rows.some((r) => r.binLabel === "")).toBe(false)
  })

  it("variable categórica: Bin array → label unido, monotonicidad null", () => {
    const d = variableBinning(binningWithTables, "segmento")
    expect(d).not.toBeNull()
    if (!d) return
    expect(d.rows).toHaveLength(2)
    expect(d.rows[0].binLabel).toBe("independiente")
    expect(d.rows[1].binLabel).toBe("asalariado")
    expect(d.monotonicity).toBeNull()
  })

  it("filtra por Count==0, NO por el nombre 'Special'/'Missing'", () => {
    // Un bin 'Special' con datos (Count>0) SÍ debe graficarse; un bin normal vacío, no.
    const binning: BinningResult = {
      n_variables_requested: 1,
      n_variables_binned: 1,
      n_variables_skipped: 0,
      iv_by_variable: { x: 0.1 },
      tables_by_variable: {
        x: [
          {
            Bin: "Special",
            Count: 12,
            "Count (%)": 0.5,
            "Non-event": 8,
            Event: 4,
            "Event rate": 0.3333,
            WoE: 0.1,
            IV: 0.01,
            JS: 0.001,
          },
          {
            Bin: "(-inf, 0)",
            Count: 0,
            "Count (%)": 0,
            "Non-event": 0,
            Event: 0,
            "Event rate": 0,
            WoE: 0.5,
            IV: 0,
            JS: 0,
          },
        ],
      },
    }
    const d = variableBinning(binning, "x")
    expect(d?.rows.map((r) => r.binLabel)).toEqual(["Special"])
  })

  it("WoE numérico no finito se normaliza a null (nunca NaN)", () => {
    const binning: BinningResult = {
      n_variables_requested: 1,
      n_variables_binned: 1,
      n_variables_skipped: 0,
      iv_by_variable: { x: 0.1 },
      tables_by_variable: {
        x: [
          {
            Bin: "(-inf, 0)",
            Count: 5,
            "Count (%)": 1,
            "Non-event": 3,
            Event: 2,
            "Event rate": 0.4,
            WoE: Number.NaN,
            IV: 0.01,
            JS: 0.001,
          },
        ],
      },
    }
    const d = variableBinning(binning, "x")
    expect(d?.rows[0].woe).toBeNull()
  })

  it("ivTotal cae a la fila Totals si falta en iv_by_variable", () => {
    const binning: BinningResult = {
      n_variables_requested: 1,
      n_variables_binned: 1,
      n_variables_skipped: 0,
      iv_by_variable: {},
      tables_by_variable: {
        x: [
          {
            Bin: "(-inf, 0)",
            Count: 5,
            "Count (%)": 0.5,
            "Non-event": 3,
            Event: 2,
            "Event rate": 0.4,
            WoE: 0.2,
            IV: 0.02,
            JS: 0.001,
          },
          {
            Bin: "",
            Count: 10,
            "Count (%)": 1,
            "Non-event": 6,
            Event: 4,
            "Event rate": 0.4,
            WoE: "",
            IV: 0.07,
            JS: 0.005,
          },
        ],
      },
    }
    const d = variableBinning(binning, "x")
    expect(d?.ivTotal).toBeCloseTo(0.07, 12)
  })

  it("devuelve null si la variable no tiene tabla o el binning falta", () => {
    expect(variableBinning(binningWithTables, "no_existe")).toBeNull()
    expect(variableBinning(undefined, "x")).toBeNull()
    expect(
      variableBinning(
        { ...binningWithTables, tables_by_variable: undefined },
        "ingreso_mensual",
      ),
    ).toBeNull()
  })
})

describe("binnedVariables", () => {
  it("lista solo las variables con tabla, ordenadas por IV desc", () => {
    const vars = binnedVariables(binningWithTables)
    expect(vars.map((v) => v.feature)).toEqual(["ingreso_mensual", "segmento"])
    expect(vars[0].iv).toBeGreaterThan(vars[1].iv)
  })

  it("IV cae a la fila Totals si falta en iv_by_variable", () => {
    const binning: BinningResult = {
      ...binningWithTables,
      iv_by_variable: {},
    }
    const vars = binnedVariables(binning)
    // ingreso_mensual (IV Totals 0.3048) sigue delante de segmento (0.0029).
    expect(vars[0].feature).toBe("ingreso_mensual")
    expect(vars[0].iv).toBeCloseTo(0.3047503805275573, 12)
  })

  it("binning ausente o sin tablas → []", () => {
    expect(binnedVariables(undefined)).toEqual([])
    expect(
      binnedVariables({ ...binningWithTables, tables_by_variable: undefined }),
    ).toEqual([])
  })
})

// --- calibración: curva de confiabilidad (reliability diagram) --------------

/** Base de `CalibrationResult` sin `reliability` (para armar fixtures del reliability). */
const calibrationBase: CalibrationResult = {
  method: "intercept_offset",
  target_pd: 0.2,
  anchor_kind: "through_the_cycle",
  anchor_source: "business_input",
  fit_partition: "desarrollo",
  n_fit: 3961,
  raw_mean_pd_dev: 0.23327442565008835,
  calibrated_mean_pd_dev: 0.2,
  observed_default_rate_dev: 0.23327442565008835,
  offset: -0.21844701788025583,
  slope: null,
  intercept: null,
  ranking_preserved: true,
  ties_created: 0,
  pd_raw_column: "pd_raw",
  pd_calibrated_column: "pd_calibrated",
  isotonic_knots: null,
}

/**
 * `calibration.reliability` con el SHAPE REAL del payload (B35a): `by_partition` como LISTA
 * y el primer bin de dev con los VALORES REALES del goal. El orden de entrada está barajado
 * (oot → desarrollo → holdout) a propósito, para verificar que el helper reordena al canónico.
 * Que compile como `CalibrationResult` ya verifica el contrato de tipos del payload.
 */
const calibrationWithReliability: CalibrationResult = {
  ...calibrationBase,
  reliability: {
    strategy: "quantile",
    n_bins: 10,
    by_partition: [
      {
        partition: "oot",
        n: 1200,
        brier: 0.1802,
        ece: 0.0512,
        bins: [
          {
            bin: 1,
            n: 120,
            mean_predicted_pd: 0.05,
            observed_default_rate: 0.07,
            ci_low: 0.03,
            ci_high: 0.11,
            pd_lo: 0.01,
            pd_hi: 0.08,
          },
        ],
      },
      {
        partition: "desarrollo",
        n: 3961,
        brier: 0.1615,
        ece: 0.0338,
        bins: [
          {
            bin: 1,
            n: 397,
            mean_predicted_pd: 0.0429,
            observed_default_rate: 0.0403,
            ci_low: 0.025,
            ci_high: 0.064,
            pd_lo: 0.0075,
            pd_hi: 0.0613,
          },
          {
            bin: 2,
            n: 396,
            mean_predicted_pd: 0.0812,
            observed_default_rate: 0.0854,
            ci_low: 0.061,
            ci_high: 0.115,
            pd_lo: 0.0614,
            pd_hi: 0.101,
          },
        ],
      },
      {
        partition: "holdout",
        n: 1000,
        brier: 0.171,
        ece: 0.0421,
        bins: [
          {
            bin: 1,
            n: 100,
            mean_predicted_pd: 0.045,
            observed_default_rate: 0.05,
            ci_low: 0.02,
            ci_high: 0.1,
            pd_lo: 0.01,
            pd_hi: 0.07,
          },
        ],
      },
    ],
  },
}

describe("reliabilityCurve", () => {
  it("normaliza el payload y reordena particiones al orden canónico", () => {
    const view = reliabilityCurve(calibrationWithReliability)
    expect(view).not.toBeNull()
    if (!view) return
    expect(view.strategy).toBe("quantile")
    expect(view.nBins).toBe(10)
    // Entrada barajada (oot, desarrollo, holdout) → salida canónica.
    expect(view.partitions.map((p) => p.partition)).toEqual([
      "desarrollo",
      "holdout",
      "oot",
    ])
  })

  it("expone los escalares Brier/ECE por partición", () => {
    const view = reliabilityCurve(calibrationWithReliability)
    const dev = view?.partitions.find((p) => p.partition === "desarrollo")
    expect(dev?.n).toBe(3961)
    expect(dev?.brier).toBeCloseTo(0.1615, 12)
    expect(dev?.ece).toBeCloseTo(0.0338, 12)
  })

  it("mapea cada bin a (pred, obs, CI, pd) y deriva el offset del error bar de Wilson", () => {
    const view = reliabilityCurve(calibrationWithReliability)
    const dev = view?.partitions.find((p) => p.partition === "desarrollo")
    expect(dev?.points).toHaveLength(2)
    const b1 = dev?.points[0]
    expect(b1?.bin).toBe(1)
    expect(b1?.n).toBe(397)
    expect(b1?.pred).toBeCloseTo(0.0429, 12)
    expect(b1?.obs).toBeCloseTo(0.0403, 12)
    expect(b1?.ciLow).toBeCloseTo(0.025, 12)
    expect(b1?.ciHigh).toBeCloseTo(0.064, 12)
    expect(b1?.pdLo).toBeCloseTo(0.0075, 12)
    expect(b1?.pdHi).toBeCloseTo(0.0613, 12)
    // ciError = [obs − ciLow, ciHigh − obs].
    expect(b1?.ciError[0]).toBeCloseTo(0.0403 - 0.025, 12)
    expect(b1?.ciError[1]).toBeCloseTo(0.064 - 0.0403, 12)
  })

  it("clampa a 0 los offsets del error bar cuando el observado cae fuera del IC", () => {
    // Bin sintético con obs < ciLow y obs > ciHigh imposible a la vez; se prueban dos bins.
    const edge: CalibrationResult = {
      ...calibrationBase,
      reliability: {
        strategy: "uniform",
        n_bins: 2,
        by_partition: [
          {
            partition: "desarrollo",
            n: 10,
            brier: 0.2,
            ece: 0.1,
            bins: [
              {
                bin: 1,
                n: 5,
                mean_predicted_pd: 0.02,
                observed_default_rate: 0.02,
                ci_low: 0.03, // obs < ci_low → offset inferior clampa a 0
                ci_high: 0.05,
                pd_lo: 0.0,
                pd_hi: 0.04,
              },
              {
                bin: 2,
                n: 5,
                mean_predicted_pd: 0.09,
                observed_default_rate: 0.09,
                ci_low: 0.05,
                ci_high: 0.08, // obs > ci_high → offset superior clampa a 0
                pd_lo: 0.06,
                pd_hi: 0.1,
              },
            ],
          },
        ],
      },
    }
    const view = reliabilityCurve(edge)
    const pts = view?.partitions[0]?.points
    expect(pts?.[0]?.ciError[0]).toBe(0)
    expect(pts?.[1]?.ciError[1]).toBe(0)
  })

  it("devuelve null si falta calibration, reliability o by_partition está vacío", () => {
    expect(reliabilityCurve(undefined)).toBeNull()
    // Calibración sin el campo reliability (backend no lo emite).
    expect(reliabilityCurve(calibrationBase)).toBeNull()
    // reliability presente pero explícitamente null.
    expect(
      reliabilityCurve({ ...calibrationBase, reliability: null }),
    ).toBeNull()
    // by_partition vacío → guard por presencia.
    expect(
      reliabilityCurve({
        ...calibrationBase,
        reliability: { strategy: "quantile", n_bins: 10, by_partition: [] },
      }),
    ).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Provisiones (SDD-28) — fixtures con VALORES REALES del preset F3
// `f3-provisiones-consumo` (recorte de un payload generado corriendo la cadena
// entera y serializado por `ui/serializers.serialize_study`). Que compilen como los
// DTOs YA verifica el contrato; sobre ellos se ejercitan los formateadores y las
// derivaciones que consume la pestaña Resultados. El titular de referencia es el
// sobrecosto: 697.376.973,92 − 308.644.057,91 = 388.732.916,01 CLP.
// ---------------------------------------------------------------------------

const provisioningSample: ProvisioningResult = {
  as_of_date: "2024-06-30",
  comparison_level: "total",
  rule: "max",
  source_a: "cmf",
  source_b: "internal",
  engines_present: ["cmf", "internal"],
  binding: "cmf",
  n_cells: 1,
  n_binding_a: 1,
  n_binding_b: 0,
  n_binding_tie: 0,
  total_provision_a: 697376973.9229127,
  total_provision_b: 308644057.91,
  total_reported_provision: 697376973.9229127,
  cmf_matrix_version: "cmf_b1_b3_2025_01",
  ifrs9_term_structure_source: null,
  internal_method: "pd_lgd",
  regulatory_sources: [
    "CNC (CMF) Cap. B-1, hoja 10-11 (Circular N° 2.346)",
    "docs/normativa_cmf_parametros.md §3",
  ],
  falta_dato: [],
  comparison: [
    {
      cell_id: "TOTAL",
      level: "total",
      source_a: "cmf",
      source_b: "internal",
      provision_a: 697376973.9229127,
      provision_b: 308644057.91,
      reported_provision: 697376973.9229127,
      binding: "cmf",
      coverage: "both",
      warning_codes: [],
    },
  ],
}

const cmfSample: CmfProvisioningResult = {
  matrix_version: "cmf_b1_b3_2025_01",
  as_of_date: "2024-06-30",
  n_rows: 6000,
  total_exposure_amount: 8079005433.76,
  total_provision_amount: 697376973.9229127,
  portfolios: [
    {
      portfolio: "consumer",
      n_rows: 6000,
      total_exposure_amount: 8079005433.76,
      total_provision_amount: 697376973.9229127,
      weighted_pe_percent: 8.631965650236614,
      warnings: [],
    },
  ],
  regulatory_sources: ["docs/normativa_cmf_parametros.md §3"],
  // Deliberadamente DESORDENADO por provisión, para ejercitar el sort de `cmfCategoryBars`.
  summary: [
    {
      portfolio: "consumer",
      method: "standard_b1",
      cmf_category: "0_7|no|yes",
      n_rows: 160,
      total_exposure_amount: 205078177.9,
      total_provision_amount: 22952502.93369726,
      weighted_pe_percent: 11.192074734001848,
      matrix_version: "cmf_b1_b3_2025_01",
      warning_codes: [],
    },
    {
      portfolio: "consumer",
      method: "standard_b1",
      cmf_category: "0_7|no|no",
      n_rows: 3302,
      total_exposure_amount: 4338485154.07,
      total_provision_amount: 160408349.38848257,
      weighted_pe_percent: 3.697335445253305,
      matrix_version: "cmf_b1_b3_2025_01",
      warning_codes: [],
    },
    {
      portfolio: "consumer",
      method: "standard_b1",
      cmf_category: "incumplimiento|yes|yes",
      n_rows: 22,
      total_exposure_amount: 37460457.85,
      total_provision_amount: 17666426.14679,
      weighted_pe_percent: 47.16019814154514,
      matrix_version: "cmf_b1_b3_2025_01",
      warning_codes: [],
    },
  ],
}

const internalSample: InternalProvisioningResult = {
  as_of_date: "2024-06-30",
  method: "pd_lgd",
  grouping: "score_band",
  pd_source: "calibration",
  n_groups: 10,
  n_rows: 6000,
  total_exposure: 8079005433.76,
  total_internal_provision: 308644057.91,
  falta_dato: [],
  groups: [
    {
      group_id: "banda_01",
      portfolio: "consumer",
      n_operations: 605,
      total_exposure: 925418827.5,
      pd_group: 0.005229006159768768,
      lgd_group: 0.4528972012939849,
      expected_loss_rate: 0.002368202255308283,
      provision_amount: 2191578.95,
      warning_codes: [],
    },
    {
      group_id: "banda_02",
      portfolio: "consumer",
      n_operations: 596,
      total_exposure: 740016129.76,
      pd_group: 0.010722703629068327,
      lgd_group: 0.4632003508928205,
      expected_loss_rate: 0.0049667600835041695,
      provision_amount: 3675482.57,
      warning_codes: [],
    },
    {
      group_id: "banda_10",
      portfolio: "consumer",
      n_operations: 600,
      total_exposure: 1037545481.31,
      pd_group: 0.3688551633807931,
      lgd_group: 0.49331411996254615,
      expected_loss_rate: 0.1819614603168371,
      provision_amount: 188793290.92,
      warning_codes: [],
    },
  ],
}

// Compila como `ResultsResponse`: verifica en tiempo de tipos que las tres claves de
// provisiones encajan en el payload top-level (el serializer las emite juntas).
const provisioningResults: ResultsResponse = {
  status: "done",
  run_id: "046cea75011443209cb4dc8686c36d8d",
  error: null,
  model_card: null,
  provisioning: provisioningSample,
  provisioning_cmf: cmfSample,
  provisioning_internal: internalSample,
}

describe("formatClp", () => {
  it("formatea CLP con separador de miles '.' y sin decimales", () => {
    expect(formatClp(388732916.0129127)).toBe("$388.732.916")
    expect(formatClp(697376973.9229127)).toBe("$697.376.974") // .92 redondea al peso
    expect(formatClp(1000)).toBe("$1.000")
    expect(formatClp(0)).toBe("$0")
  })

  it("respeta el signo de un monto negativo", () => {
    expect(formatClp(-388732916)).toBe("-$388.732.916")
  })

  it("ausente/no finito → EMPTY", () => {
    expect(formatClp(null)).toBe(EMPTY)
    expect(formatClp(undefined)).toBe(EMPTY)
    expect(formatClp(Number.NaN)).toBe(EMPTY)
    expect(formatClp(Number.POSITIVE_INFINITY)).toBe(EMPTY)
  })
})

describe("formatClpCompact", () => {
  it("formatea CLP compacto en millones con separador de miles", () => {
    expect(formatClpCompact(697376973.92)).toBe("$697 M")
    expect(formatClpCompact(8079005433.76)).toBe("$8.079 M")
    expect(formatClpCompact(2191578.95)).toBe("$2 M")
    expect(formatClpCompact(388732916.01)).toBe("$389 M")
  })

  it("ausente/no finito → EMPTY", () => {
    expect(formatClpCompact(null)).toBe(EMPTY)
    expect(formatClpCompact(Number.NaN)).toBe(EMPTY)
  })
})

describe("formatPercentValue", () => {
  it("formatea un valor que YA es porcentaje sin reescalar", () => {
    expect(formatPercentValue(8.631965650236614)).toBe("8.63%")
    expect(formatPercentValue(47.16019814154514, 1)).toBe("47.2%")
    expect(formatPercentValue(3.697335445253305, 0)).toBe("4%")
  })

  it("ausente/no finito → EMPTY", () => {
    expect(formatPercentValue(null)).toBe(EMPTY)
    expect(formatPercentValue(Number.NaN)).toBe(EMPTY)
  })
})

describe("provisioningSourceLabel", () => {
  it("etiqueta las fuentes conocidas y cae al slug para las nuevas", () => {
    expect(provisioningSourceLabel("cmf")).toBe("Estándar (CMF)")
    expect(provisioningSourceLabel("internal")).toBe("Interno")
    expect(provisioningSourceLabel("ifrs9")).toBe("IFRS 9 (ECL)")
    expect(provisioningSourceLabel("desconocida")).toBe("desconocida")
  })
})

describe("scoreBandLabel", () => {
  it("humaniza la banda de score y cae al id crudo si no calza", () => {
    expect(scoreBandLabel("banda_01")).toBe("Banda 1")
    expect(scoreBandLabel("banda_10")).toBe("Banda 10")
    expect(scoreBandLabel("otro")).toBe("otro")
  })
})

describe("cmfCategoryLabel", () => {
  it("decodea el código (bucket|hipotecario|mora) a una etiqueta legible", () => {
    expect(cmfCategoryLabel("0_7|no|no")).toBe("0–7 d · Hip No · MoraS No")
    expect(cmfCategoryLabel("0_7|no|yes")).toBe("0–7 d · Hip No · MoraS Sí")
    expect(cmfCategoryLabel("incumplimiento|yes|yes")).toBe(
      "Incumpl. · Hip Sí · MoraS Sí",
    )
  })

  it("cae al código crudo si no tiene tres partes", () => {
    expect(cmfCategoryLabel("raro")).toBe("raro")
    expect(cmfCategoryLabel("a|b")).toBe("a|b")
  })
})

describe("provisioningHeadline", () => {
  it("resume la regla del máximo: el sobrecosto = reportada − interna (CLP)", () => {
    const h = provisioningHeadline(provisioningResults.provisioning)
    expect(h).not.toBeNull()
    expect(h?.reported).toBe(697376973.9229127)
    expect(h?.standard).toBe(697376973.9229127)
    expect(h?.internal).toBe(308644057.91)
    expect(h?.overcost).toBeCloseTo(388732916.0129127, 4)
    expect(h?.overcostVsInternal).toBeCloseTo(1.2595, 3)
    expect(h?.binding).toBe("cmf")
    expect(h?.sourceA).toBe("cmf")
    expect(h?.sourceB).toBe("internal")
    // El titular formateado que ve el gerente.
    expect(formatClp(h?.overcost)).toBe("$388.732.916")
  })

  it("null cuando la card falta o un total no es finito (guard por presencia)", () => {
    expect(provisioningHeadline(null)).toBeNull()
    expect(provisioningHeadline(undefined)).toBeNull()
    expect(
      provisioningHeadline({
        ...provisioningSample,
        total_reported_provision: Number.NaN,
      }),
    ).toBeNull()
  })
})

describe("provisioningComparisonBars", () => {
  it("emite estándar/interno/reportado y marca cuál manda", () => {
    const bars = provisioningComparisonBars(provisioningResults.provisioning)
    expect(bars.map((b) => b.key)).toEqual(["standard", "internal", "reported"])
    expect(bars[0]).toMatchObject({
      label: "Estándar (CMF)",
      value: 697376973.9229127,
      binding: true, // binding === source_a
    })
    expect(bars[1]).toMatchObject({
      label: "Interno",
      value: 308644057.91,
      binding: false,
    })
    expect(bars[2]).toMatchObject({
      label: "Reportado (norma)",
      value: 697376973.9229127,
      binding: true,
    })
  })

  it("[] cuando la card falta", () => {
    expect(provisioningComparisonBars(null)).toEqual([])
    expect(provisioningComparisonBars(undefined)).toEqual([])
  })
})

describe("internalGroupBars", () => {
  it("proyecta los grupos preservando el orden del motor (banda_01 → banda_10)", () => {
    const bars = internalGroupBars(provisioningResults.provisioning_internal)
    expect(bars).toHaveLength(3)
    expect(bars.map((b) => b.label)).toEqual(["Banda 1", "Banda 2", "Banda 10"])
    expect(bars[0]).toMatchObject({
      group: "banda_01",
      provision: 2191578.95,
      pd: 0.005229006159768768,
      lgd: 0.4528972012939849,
      exposure: 925418827.5,
      n: 605,
    })
    expect(bars[2]?.provision).toBe(188793290.92)
  })

  it("[] cuando falta la card o el frame de grupos", () => {
    expect(internalGroupBars(null)).toEqual([])
    expect(
      internalGroupBars({ ...internalSample, groups: undefined }),
    ).toEqual([])
  })
})

describe("cmfCategoryBars", () => {
  it("ordena las categorías por provisión DESC y decodea la etiqueta", () => {
    const bars = cmfCategoryBars(provisioningResults.provisioning_cmf)
    expect(bars.map((b) => b.category)).toEqual([
      "0_7|no|no", // 160 M
      "0_7|no|yes", // 23 M
      "incumplimiento|yes|yes", // 18 M
    ])
    expect(bars[0]).toMatchObject({
      label: "0–7 d · Hip No · MoraS No",
      provision: 160408349.38848257,
      exposure: 4338485154.07,
      weightedPe: 3.697335445253305,
      n: 3302,
    })
  })

  it("[] cuando falta la card o el frame de resumen", () => {
    expect(cmfCategoryBars(null)).toEqual([])
    expect(cmfCategoryBars({ ...cmfSample, summary: undefined })).toEqual([])
  })
})
