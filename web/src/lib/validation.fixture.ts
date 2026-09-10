/**
 * Validación formal con VALORES REALES: la clave `validation` de `GET /api/results/<run_id>` de
 * una corrida del esqueleto del trabajo «Scorecard de comportamiento (PD)» sobre
 * `consumo_comportamiento` (6.000 filas, tres particiones por cohorte).
 *
 * 🔴 Su `overall_status` es `fail`, y no es un fixture cómodo: el Hosmer-Lemeshow rechaza en la
 * partición fuera de tiempo —deriva temporal legítima de la cartera— y el panel tiene que
 * publicarlo tal cual. Un fixture en verde habría dejado sin probar la única rama que importa.
 *
 * Es sólo para tests: los fixtures de la demo se capturaron antes de que el serializer emitiera
 * esta clave y no se recapturan sin un OK propio (D-GOB-9), así que el panel tiene además que
 * renderizar SIN ella. Que este objeto compile como `ValidationResult` ya es una verificación del
 * contrato: si el tipo dejara de reflejar lo que el serializer emite, `tsc` fallaría aquí.
 */

import type { ValidationResult } from "@/lib/results-types"

export const VALIDATION_F1: ValidationResult = {
  "model_ref": "nikodym-study",
  "families_run": [
    "discrimination",
    "calibration",
    "stability"
  ],
  "overall_status": "fail",
  "n_tests": 3,
  "n_failed": 1,
  "dependency_versions": {
    "numpy": "2.4.6",
    "pandas": "2.3.3",
    "scipy": "1.18.0"
  },
  "falta_dato": [],
  "metric_sections": {
    "validation": {
      "families_run": [
        "discrimination",
        "calibration",
        "stability"
      ],
      "overall_status": "fail",
      "n_tests": 3,
      "n_failed": 1,
      "traffic_light": {
        "green": 0,
        "amber": 0,
        "red": 0
      },
      "not_evaluable_grades": []
    }
  },
  "discrimination": [
    {
      "partition": "desarrollo",
      "n_total": 4019,
      "n_bad": 920,
      "auc": 0.7127514836483018,
      "gini": 0.42550296729660353,
      "ks": 0.3151062053677904,
      "source": "performance_artifact",
      "status": "ok"
    },
    {
      "partition": "holdout",
      "n_total": 973,
      "n_bad": 248,
      "auc": 0.6767686318131256,
      "gini": 0.35353726362625126,
      "ks": 0.2557842046718576,
      "source": "performance_artifact",
      "status": "ok"
    },
    {
      "partition": "oot",
      "n_total": 1008,
      "n_bad": 239,
      "auc": 0.6504535042521125,
      "gini": 0.3009070085042249,
      "ks": 0.2210391150818049,
      "source": "performance_artifact",
      "status": "ok"
    }
  ],
  "calibration": [
    {
      "partition": "desarrollo",
      "test": "hosmer_lemeshow",
      "grade": "ALL",
      "n": 4019,
      "observed_defaults": 920,
      "expected_pd": 0.22891266484200049,
      "observed_dr": 0.22891266484200049,
      "statistic": 13.678690381237846,
      "degrees_of_freedom": 8,
      "p_value": 0.09053429506727678,
      "alpha": 0.05,
      "decision": "pass",
      "traffic_light": null
    },
    {
      "partition": "desarrollo",
      "test": "brier",
      "grade": "ALL",
      "n": 4019,
      "observed_defaults": 920,
      "expected_pd": 0.22891266484200049,
      "observed_dr": 0.22891266484200049,
      "statistic": 0.15810191389607378,
      "degrees_of_freedom": null,
      "p_value": null,
      "alpha": null,
      "decision": "not_evaluable",
      "traffic_light": null
    },
    {
      "partition": "holdout",
      "test": "hosmer_lemeshow",
      "grade": "ALL",
      "n": 973,
      "observed_defaults": 248,
      "expected_pd": 0.23829441081057545,
      "observed_dr": 0.25488180883864336,
      "statistic": 9.469648680541601,
      "degrees_of_freedom": 8,
      "p_value": 0.30423733143566495,
      "alpha": 0.05,
      "decision": "pass",
      "traffic_light": null
    },
    {
      "partition": "holdout",
      "test": "brier",
      "grade": "ALL",
      "n": 973,
      "observed_defaults": 248,
      "expected_pd": 0.23829441081057545,
      "observed_dr": 0.25488180883864336,
      "statistic": 0.17590434512612255,
      "degrees_of_freedom": null,
      "p_value": null,
      "alpha": null,
      "decision": "not_evaluable",
      "traffic_light": null
    },
    {
      "partition": "oot",
      "test": "hosmer_lemeshow",
      "grade": "ALL",
      "n": 1008,
      "observed_defaults": 239,
      "expected_pd": 0.22960779838344889,
      "observed_dr": 0.2371031746031746,
      "statistic": 18.2020951185521,
      "degrees_of_freedom": 8,
      "p_value": 0.019761346762050585,
      "alpha": 0.05,
      "decision": "fail",
      "traffic_light": null
    },
    {
      "partition": "oot",
      "test": "brier",
      "grade": "ALL",
      "n": 1008,
      "observed_defaults": 239,
      "expected_pd": 0.22960779838344889,
      "observed_dr": 0.2371031746031746,
      "statistic": 0.17247744437103188,
      "degrees_of_freedom": null,
      "p_value": null,
      "alpha": null,
      "decision": "not_evaluable",
      "traffic_light": null
    }
  ],
  "stability": [
    {
      "metric": "score_psi",
      "comparison": "dev_vs_holdout",
      "feature": "score",
      "value": 0.01893562170038972,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    },
    {
      "metric": "score_psi",
      "comparison": "dev_vs_oot",
      "feature": "score",
      "value": 0.008178478372343128,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    },
    {
      "metric": "pd_psi",
      "comparison": "dev_vs_holdout",
      "feature": "pd_calibrated",
      "value": 0.020933473377463124,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    },
    {
      "metric": "pd_psi",
      "comparison": "dev_vs_oot",
      "feature": "pd_calibrated",
      "value": 0.009545409817530106,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    },
    {
      "metric": "csi",
      "comparison": "dev_vs_holdout",
      "feature": "antiguedad_meses__points",
      "value": 0.007256346004447214,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    },
    {
      "metric": "csi",
      "comparison": "dev_vs_oot",
      "feature": "antiguedad_meses__points",
      "value": 0.004711598318210877,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    },
    {
      "metric": "csi",
      "comparison": "dev_vs_holdout",
      "feature": "deuda_ingreso__points",
      "value": 0.010901063939643664,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    },
    {
      "metric": "csi",
      "comparison": "dev_vs_oot",
      "feature": "deuda_ingreso__points",
      "value": 0.008407491171352683,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    },
    {
      "metric": "csi",
      "comparison": "dev_vs_holdout",
      "feature": "ingreso_mensual__points",
      "value": 0.008197216306108842,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    },
    {
      "metric": "csi",
      "comparison": "dev_vs_oot",
      "feature": "ingreso_mensual__points",
      "value": 0.013419150906540982,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    },
    {
      "metric": "csi",
      "comparison": "dev_vs_holdout",
      "feature": "utilizacion_linea__points",
      "value": 0.003128477786037453,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    },
    {
      "metric": "csi",
      "comparison": "dev_vs_oot",
      "feature": "utilizacion_linea__points",
      "value": 0.012164314353667239,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    },
    {
      "metric": "temporal_score",
      "comparison": "period",
      "feature": "score",
      "value": 0.00957575099020254,
      "stable_threshold": 0.1,
      "review_threshold": 0.25,
      "band": "stable",
      "action": "none",
      "source": "stability_artifact",
      "status": "ok",
      "decision": "pass"
    }
  ],
  "backtesting": []
}
