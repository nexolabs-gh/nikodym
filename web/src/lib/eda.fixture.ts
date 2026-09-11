/**
 * El bloque `eda` de `/api/results` de una corrida REAL del esqueleto del trabajo «Scorecard de
 * comportamiento (PD)» sobre `consumo_comportamiento` (6.000 operaciones, partición por cohorte),
 * con los defaults de la sección: `axis="period"` sin columna de fecha, así que el motor tomó la
 * cohorte de la partición (D-SC-3) y la señal temporal quedó sin evaluar por `eje_cohorte`
 * (D-SC-2). Capturado el 2026-09-11 (capa 3 del scorecard completo) y recapturado el mismo día
 * cuando la fila de la tasa ganó `period_type`; `stability_value` llega `null` porque el
 * serializer publica el `NaN` del motor como ausencia.
 *
 * Es el caso «cohorte inferida» de los tres que §6 de la enmienda pide gatear; los otros dos se
 * derivan de éste en el test cambiando sólo la card, porque son la misma corrida vista con otro
 * eje.
 */

import type { EdaResult } from "@/lib/results-types"

export const EDA_SCORECARD_REAL: EdaResult = {
  "overall_default_rate": 0.22891266484200049,
  "n_periods": 5,
  "stability_flagged": false,
  "stability_metric_used": "cv",
  "stability_threshold": 0.25,
  "stability_value": null,
  "n_columns_profiled": 6,
  "quality_flag_counts": {
    "near_constant": 2,
    "near_unique": 1,
    "high_cardinality": 0
  },
  "n_figures": 6,
  "axis": "cohort",
  "axis_inferred": true,
  "stability_not_evaluable_reason": "eje_cohorte",
  "default_rate": [
    {
      "period": "2023Q1",
      "n_total": 815,
      "n_eligible": 815,
      "n_bad": 187,
      "default_rate": 0.2294478527607362,
      "low_confidence": false,
      "period_type": "str"
    },
    {
      "period": "2023Q2",
      "n_total": 822,
      "n_eligible": 822,
      "n_bad": 181,
      "default_rate": 0.22019464720194648,
      "low_confidence": false,
      "period_type": "str"
    },
    {
      "period": "2023Q3",
      "n_total": 819,
      "n_eligible": 819,
      "n_bad": 180,
      "default_rate": 0.21978021978021978,
      "low_confidence": false,
      "period_type": "str"
    },
    {
      "period": "2023Q4",
      "n_total": 801,
      "n_eligible": 801,
      "n_bad": 188,
      "default_rate": 0.23470661672908863,
      "low_confidence": false,
      "period_type": "str"
    },
    {
      "period": "2024Q1",
      "n_total": 762,
      "n_eligible": 762,
      "n_bad": 184,
      "default_rate": 0.24146981627296588,
      "low_confidence": false,
      "period_type": "str"
    }
  ],
  "quality": [
    {
      "col": "ingreso_mensual",
      "dtype": "float64",
      "missing_rate": 0.0,
      "cardinality": 4019,
      "near_constant": false,
      "near_unique": true,
      "high_cardinality": false
    },
    {
      "col": "deuda_ingreso",
      "dtype": "float64",
      "missing_rate": 0.0,
      "cardinality": 3097,
      "near_constant": false,
      "near_unique": false,
      "high_cardinality": false
    },
    {
      "col": "utilizacion_linea",
      "dtype": "float64",
      "missing_rate": 0.0,
      "cardinality": 3089,
      "near_constant": false,
      "near_unique": false,
      "high_cardinality": false
    },
    {
      "col": "mora_max_12m",
      "dtype": "int64",
      "missing_rate": 0.0,
      "cardinality": 18,
      "near_constant": false,
      "near_unique": false,
      "high_cardinality": false
    },
    {
      "col": "antiguedad_meses",
      "dtype": "int64",
      "missing_rate": 0.0,
      "cardinality": 120,
      "near_constant": false,
      "near_unique": false,
      "high_cardinality": false
    },
    {
      "col": "segmento",
      "dtype": "object",
      "missing_rate": 0.0,
      "cardinality": 3,
      "near_constant": false,
      "near_unique": false,
      "high_cardinality": false
    },
    {
      "col": "cohorte",
      "dtype": "object",
      "missing_rate": 0.0,
      "cardinality": 5,
      "near_constant": false,
      "near_unique": false,
      "high_cardinality": false
    },
    {
      "col": "bad_flag",
      "dtype": "int64",
      "missing_rate": 0.0,
      "cardinality": 2,
      "near_constant": false,
      "near_unique": false,
      "high_cardinality": false
    },
    {
      "col": "target",
      "dtype": "Int8",
      "missing_rate": 0.0,
      "cardinality": 2,
      "near_constant": false,
      "near_unique": false,
      "high_cardinality": false
    },
    {
      "col": "label_status",
      "dtype": "category",
      "missing_rate": 0.0,
      "cardinality": 2,
      "near_constant": false,
      "near_unique": false,
      "high_cardinality": false
    },
    {
      "col": "partition",
      "dtype": "category",
      "missing_rate": 0.0,
      "cardinality": 1,
      "near_constant": true,
      "near_unique": false,
      "high_cardinality": false
    },
    {
      "col": "ttd",
      "dtype": "bool",
      "missing_rate": 0.0,
      "cardinality": 1,
      "near_constant": true,
      "near_unique": false,
      "high_cardinality": false
    }
  ],
  "univariate": [
    {
      "column": "ingreso_mensual",
      "tramo": "(74032.56, 286535.966]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.3756218905472637,
      "descriptive_iv": null
    },
    {
      "column": "ingreso_mensual",
      "tramo": "(286535.966, 353899.07]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.3656716417910448,
      "descriptive_iv": null
    },
    {
      "column": "ingreso_mensual",
      "tramo": "(353899.07, 410815.70999999996]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.2935323383084577,
      "descriptive_iv": null
    },
    {
      "column": "ingreso_mensual",
      "tramo": "(410815.70999999996, 464102.74600000004]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.25870646766169153,
      "descriptive_iv": null
    },
    {
      "column": "ingreso_mensual",
      "tramo": "(464102.74600000004, 528696.61]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.22388059701492538,
      "descriptive_iv": null
    },
    {
      "column": "ingreso_mensual",
      "tramo": "(528696.61, 603120.5000000001]",
      "n": 401,
      "coverage": 0.09977606369743718,
      "default_rate": 0.20199501246882792,
      "descriptive_iv": null
    },
    {
      "column": "ingreso_mensual",
      "tramo": "(603120.5000000001, 694955.146]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.16666666666666666,
      "descriptive_iv": null
    },
    {
      "column": "ingreso_mensual",
      "tramo": "(694955.146, 814788.054]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.16169154228855723,
      "descriptive_iv": null
    },
    {
      "column": "ingreso_mensual",
      "tramo": "(814788.054, 1017596.2840000002]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.1318407960199005,
      "descriptive_iv": null
    },
    {
      "column": "ingreso_mensual",
      "tramo": "(1017596.2840000002, 3524342.26]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.10945273631840796,
      "descriptive_iv": null
    },
    {
      "column": "deuda_ingreso",
      "tramo": "(0.0018, 0.09518]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.1691542288557214,
      "descriptive_iv": null
    },
    {
      "column": "deuda_ingreso",
      "tramo": "(0.09518, 0.14822]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.16666666666666666,
      "descriptive_iv": null
    },
    {
      "column": "deuda_ingreso",
      "tramo": "(0.14822, 0.1999]",
      "n": 403,
      "coverage": 0.10027369992535456,
      "default_rate": 0.18610421836228289,
      "descriptive_iv": null
    },
    {
      "column": "deuda_ingreso",
      "tramo": "(0.1999, 0.25142000000000003]",
      "n": 401,
      "coverage": 0.09977606369743718,
      "default_rate": 0.1745635910224439,
      "descriptive_iv": null
    },
    {
      "column": "deuda_ingreso",
      "tramo": "(0.25142000000000003, 0.3072]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.2263681592039801,
      "descriptive_iv": null
    },
    {
      "column": "deuda_ingreso",
      "tramo": "(0.3072, 0.3646]",
      "n": 403,
      "coverage": 0.10027369992535456,
      "default_rate": 0.18362282878411912,
      "descriptive_iv": null
    },
    {
      "column": "deuda_ingreso",
      "tramo": "(0.3646, 0.445]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.24378109452736318,
      "descriptive_iv": null
    },
    {
      "column": "deuda_ingreso",
      "tramo": "(0.445, 0.5347000000000001]",
      "n": 400,
      "coverage": 0.09952724558347847,
      "default_rate": 0.2575,
      "descriptive_iv": null
    },
    {
      "column": "deuda_ingreso",
      "tramo": "(0.5347000000000001, 0.6984600000000001]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.2960199004975124,
      "descriptive_iv": null
    },
    {
      "column": "deuda_ingreso",
      "tramo": "(0.6984600000000001, 1.7973]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.3855721393034826,
      "descriptive_iv": null
    },
    {
      "column": "utilizacion_linea",
      "tramo": "(0.0041, 0.13678]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.15671641791044777,
      "descriptive_iv": null
    },
    {
      "column": "utilizacion_linea",
      "tramo": "(0.13678, 0.21432]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.20149253731343283,
      "descriptive_iv": null
    },
    {
      "column": "utilizacion_linea",
      "tramo": "(0.21432, 0.277]",
      "n": 403,
      "coverage": 0.10027369992535456,
      "default_rate": 0.18114143920595532,
      "descriptive_iv": null
    },
    {
      "column": "utilizacion_linea",
      "tramo": "(0.277, 0.33326]",
      "n": 401,
      "coverage": 0.09977606369743718,
      "default_rate": 0.24189526184538654,
      "descriptive_iv": null
    },
    {
      "column": "utilizacion_linea",
      "tramo": "(0.33326, 0.3886]",
      "n": 404,
      "coverage": 0.10052251803931327,
      "default_rate": 0.18564356435643564,
      "descriptive_iv": null
    },
    {
      "column": "utilizacion_linea",
      "tramo": "(0.3886, 0.44466]",
      "n": 399,
      "coverage": 0.09927842746951979,
      "default_rate": 0.22055137844611528,
      "descriptive_iv": null
    },
    {
      "column": "utilizacion_linea",
      "tramo": "(0.44466, 0.50862]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.26865671641791045,
      "descriptive_iv": null
    },
    {
      "column": "utilizacion_linea",
      "tramo": "(0.50862, 0.5782]",
      "n": 403,
      "coverage": 0.10027369992535456,
      "default_rate": 0.24069478908188585,
      "descriptive_iv": null
    },
    {
      "column": "utilizacion_linea",
      "tramo": "(0.5782, 0.66754]",
      "n": 401,
      "coverage": 0.09977606369743718,
      "default_rate": 0.286783042394015,
      "descriptive_iv": null
    },
    {
      "column": "utilizacion_linea",
      "tramo": "(0.66754, 0.9724]",
      "n": 402,
      "coverage": 0.10002488181139586,
      "default_rate": 0.30597014925373134,
      "descriptive_iv": null
    },
    {
      "column": "mora_max_12m",
      "tramo": "(0.0, 3.0]",
      "n": 619,
      "coverage": 0.15401841254043294,
      "default_rate": 0.19063004846526657,
      "descriptive_iv": null
    },
    {
      "column": "mora_max_12m",
      "tramo": "(3.0, 4.0]",
      "n": 541,
      "coverage": 0.13461059965165464,
      "default_rate": 0.21072088724584104,
      "descriptive_iv": null
    },
    {
      "column": "mora_max_12m",
      "tramo": "(4.0, 5.0]",
      "n": 637,
      "coverage": 0.15849713859168948,
      "default_rate": 0.22135007849293564,
      "descriptive_iv": null
    },
    {
      "column": "mora_max_12m",
      "tramo": "(5.0, 6.0]",
      "n": 665,
      "coverage": 0.16546404578253296,
      "default_rate": 0.23157894736842105,
      "descriptive_iv": null
    },
    {
      "column": "mora_max_12m",
      "tramo": "(6.0, 7.0]",
      "n": 547,
      "coverage": 0.13610350833540683,
      "default_rate": 0.24862888482632542,
      "descriptive_iv": null
    },
    {
      "column": "mora_max_12m",
      "tramo": "(7.0, 8.0]",
      "n": 377,
      "coverage": 0.09380442896242847,
      "default_rate": 0.2519893899204244,
      "descriptive_iv": null
    },
    {
      "column": "mora_max_12m",
      "tramo": "(8.0, 9.0]",
      "n": 288,
      "coverage": 0.07165961682010451,
      "default_rate": 0.2465277777777778,
      "descriptive_iv": null
    },
    {
      "column": "mora_max_12m",
      "tramo": "(9.0, 17.0]",
      "n": 345,
      "coverage": 0.08584224931575019,
      "default_rate": 0.263768115942029,
      "descriptive_iv": null
    },
    {
      "column": "antiguedad_meses",
      "tramo": "(1.0, 13.0]",
      "n": 424,
      "coverage": 0.10549888031848718,
      "default_rate": 0.2830188679245283,
      "descriptive_iv": null
    },
    {
      "column": "antiguedad_meses",
      "tramo": "(13.0, 25.0]",
      "n": 383,
      "coverage": 0.09529733764618065,
      "default_rate": 0.2297650130548303,
      "descriptive_iv": null
    },
    {
      "column": "antiguedad_meses",
      "tramo": "(25.0, 37.0]",
      "n": 400,
      "coverage": 0.09952724558347847,
      "default_rate": 0.2825,
      "descriptive_iv": null
    },
    {
      "column": "antiguedad_meses",
      "tramo": "(37.0, 49.0]",
      "n": 412,
      "coverage": 0.10251306295098284,
      "default_rate": 0.22572815533980584,
      "descriptive_iv": null
    },
    {
      "column": "antiguedad_meses",
      "tramo": "(49.0, 62.0]",
      "n": 422,
      "coverage": 0.1050012440905698,
      "default_rate": 0.25829383886255924,
      "descriptive_iv": null
    },
    {
      "column": "antiguedad_meses",
      "tramo": "(62.0, 73.0]",
      "n": 383,
      "coverage": 0.09529733764618065,
      "default_rate": 0.20887728459530025,
      "descriptive_iv": null
    },
    {
      "column": "antiguedad_meses",
      "tramo": "(73.0, 85.0]",
      "n": 407,
      "coverage": 0.10126897238118936,
      "default_rate": 0.23832923832923833,
      "descriptive_iv": null
    },
    {
      "column": "antiguedad_meses",
      "tramo": "(85.0, 97.0]",
      "n": 417,
      "coverage": 0.10375715352077632,
      "default_rate": 0.22302158273381295,
      "descriptive_iv": null
    },
    {
      "column": "antiguedad_meses",
      "tramo": "(97.0, 108.0]",
      "n": 375,
      "coverage": 0.09330679273451108,
      "default_rate": 0.168,
      "descriptive_iv": null
    },
    {
      "column": "antiguedad_meses",
      "tramo": "(108.0, 120.0]",
      "n": 396,
      "coverage": 0.0985319731276437,
      "default_rate": 0.16161616161616163,
      "descriptive_iv": null
    },
    {
      "column": "segmento",
      "tramo": "asalariado",
      "n": 1330,
      "coverage": 0.3309280915650659,
      "default_rate": 0.22631578947368422,
      "descriptive_iv": null
    },
    {
      "column": "segmento",
      "tramo": "independiente",
      "n": 1372,
      "coverage": 0.3413784523513312,
      "default_rate": 0.22448979591836735,
      "descriptive_iv": null
    },
    {
      "column": "segmento",
      "tramo": "pensionado",
      "n": 1317,
      "coverage": 0.3276934560836029,
      "default_rate": 0.23614274867122248,
      "descriptive_iv": null
    }
  ]
}
