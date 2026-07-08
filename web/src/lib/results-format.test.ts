import { describe, expect, it } from "vitest"

import {
  EMPTY,
  discriminantRows,
  formatBool,
  formatCount,
  formatMetric,
  formatPValue,
  formatPercent,
  sortByIv,
} from "./results-format"
import type { ResultsResponse } from "./results-types"

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
  })
})
