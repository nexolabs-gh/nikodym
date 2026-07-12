/**
 * Evidencia de la landing: TODO dato de esta página sale de una corrida REAL del motor
 * (el fixture `src/fixtures/demo/results.json`, dataset sintético de consumo, partición
 * holdout). Se copian aquí como constantes en vez de importar el fixture (120 KB) para no
 * meterlo en el bundle de la primera pantalla.
 *
 * REGLA: si un número de aquí no se puede rastrear a una corrida real, no va. Nunca se
 * inventa una cifra en una superficie pública de un producto de riesgo.
 */

/** Curva de gains, partición holdout (fuera de muestra). `capturado` = cum_bad_capture_rate. */
export const GAINS_HOLDOUT: readonly { decil: number; capturado: number }[] = [
  { decil: 1, capturado: 21.3 },
  { decil: 2, capturado: 38.1 },
  { decil: 3, capturado: 52.0 },
  { decil: 4, capturado: 62.3 },
  { decil: 5, capturado: 71.3 },
  { decil: 6, capturado: 76.6 },
  { decil: 7, capturado: 86.1 },
  { decil: 8, capturado: 92.2 },
  { decil: 9, capturado: 96.3 },
  { decil: 10, capturado: 100.0 },
]

/** Métricas de la misma corrida. Holdout = fuera de muestra (el número honesto). */
export const METRICAS = [
  { clave: "AUC", valor: "0,695", nota: "holdout" },
  { clave: "KS", valor: "0,312", nota: "holdout" },
  { clave: "PSI", valor: "0,013", nota: "dev vs holdout" },
] as const

/** Los 6 pasos del pipeline, con la evidencia real de la corrida en la última columna. */
export const PIPELINE = [
  {
    n: "01",
    paso: "Datos",
    hace: "Carga, validación de esquema y partición dev / holdout / OOT.",
    dato: "3.961 obs · 924 eventos",
  },
  {
    n: "02",
    paso: "Binning",
    hace: "Discretización WoE con monotonicidad e IV por variable.",
    dato: "6 variables",
  },
  {
    n: "03",
    paso: "Selección",
    hace: "Descarte por IV, colinealidad (VIF) y estabilidad.",
    dato: "6 → 5 variables",
  },
  {
    n: "04",
    paso: "Modelo",
    hace: "Regresión logística sobre WoE, escalada a scorecard (PDO / offset).",
    dato: "5 features finales",
  },
  {
    n: "05",
    paso: "Calibración",
    hace: "PD calibrada a la tasa objetivo, con curva de reliability.",
    dato: "PD media 20,0 %",
  },
  {
    n: "06",
    paso: "Informe",
    hace: "Documento con metodología y resultados. HTML, PDF y base editable.",
    dato: "5 capítulos + anexos",
  },
] as const

/** Capítulos del informe que produce el motor. */
export const CAPITULOS = [
  { n: "1", titulo: "Introducción", tipo: "editable" },
  { n: "2", titulo: "Contexto", tipo: "editable" },
  { n: "3", titulo: "Metodología", tipo: "generado" },
  { n: "4", titulo: "Resultados", tipo: "generado" },
  { n: "5", titulo: "Conclusiones", tipo: "editable" },
  { n: "A", titulo: "Anexos técnicos", tipo: "generado" },
] as const

/**
 * El quickstart REAL. Este código se ejecutó contra el motor instalado antes de publicarlo
 * aquí y devuelve `done`. Si se cambia una línea, se vuelve a ejecutar: una landing que
 * muestra código que no corre es una mentira, y este producto se vende por ser verificable.
 *
 * Cada línea es una lista de tokens: `c` es la clase de color (ver CLASE_TOKEN).
 */
export const CODIGO: readonly (readonly { t: string; c: string }[])[] = [
  [
    { t: "from", c: "kw" },
    { t: " pathlib ", c: "id" },
    { t: "import", c: "kw" },
    { t: " Path", c: "id" },
  ],
  [],
  [
    { t: "import", c: "kw" },
    { t: " nikodym", c: "id" },
  ],
  [
    { t: "from", c: "kw" },
    { t: " nikodym.core.config ", c: "id" },
    { t: "import", c: "kw" },
    { t: " NikodymConfig", c: "id" },
  ],
  [
    { t: "from", c: "kw" },
    { t: " nikodym.ui.datasets ", c: "id" },
    { t: "import", c: "kw" },
    { t: " materialize", c: "id" },
  ],
  [
    { t: "from", c: "kw" },
    { t: " nikodym.ui.presets ", c: "id" },
    { t: "import", c: "kw" },
    { t: " standard_preset", c: "id" },
  ],
  [],
  [
    { t: "preset", c: "id" },
    { t: " = ", c: "p" },
    { t: "standard_preset", c: "fn" },
    { t: "()", c: "p" },
  ],
  [
    { t: "datos", c: "id" },
    { t: " = ", c: "p" },
    { t: "materialize", c: "fn" },
    { t: "(", c: "p" },
  ],
  [
    { t: "    preset", c: "id" },
    { t: "[", c: "p" },
    { t: '"dataset_id"', c: "str" },
    { t: "],", c: "p" },
  ],
  [
    { t: "    workdir=", c: "p" },
    { t: "Path", c: "fn" },
    { t: "(", c: "p" },
    { t: '"runs"', c: "str" },
    { t: "),", c: "p" },
  ],
  [{ t: ")", c: "p" }],
  [],
  [
    { t: "cfg", c: "id" },
    { t: " = preset[", c: "p" },
    { t: '"config"', c: "str" },
    { t: "]", c: "p" },
  ],
  [
    { t: "cfg", c: "id" },
    { t: "[", c: "p" },
    { t: '"data"', c: "str" },
    { t: "][", c: "p" },
    { t: '"load"', c: "str" },
    { t: "][", c: "p" },
    { t: '"source"', c: "str" },
    { t: "] = ", c: "p" },
    { t: "str", c: "fn" },
    { t: "(datos)", c: "p" },
  ],
  [],
  [
    { t: "config", c: "id" },
    { t: " = NikodymConfig.", c: "p" },
    { t: "model_validate", c: "fn" },
    { t: "(cfg)", c: "p" },
  ],
  [
    { t: "study", c: "id" },
    { t: " = nikodym.", c: "p" },
    { t: "run", c: "fn" },
    { t: "(config)", c: "p" },
  ],
  [],
  [{ t: "study", c: "id" }, { t: ".run_context.status", c: "p" }],
  [{ t: "# 'done'  ·  reproducible por config_hash", c: "cm" }],
]

/** Dominios del motor. `scorecard` tiene UI; el resto se usa hoy desde Python. */
export const DOMINIOS = [
  {
    key: "forward",
    label: "Forward-looking",
    tagline: "Proyección PD/LGD multi-escenario y ECL bajo IFRS 9.",
    modulo: "nikodym.forward",
  },
  {
    key: "markov",
    label: "Matrices de transición",
    tagline: "Cadenas de Markov, matrices CMF y term-structures de migración.",
    modulo: "nikodym.markov",
  },
  {
    key: "stress",
    label: "Stress testing",
    tagline: "Escenarios adversos, reverse-stress y sensibilidad del portafolio.",
    modulo: "nikodym.stress",
  },
  {
    key: "survival",
    label: "Survival",
    tagline: "Tiempo-a-evento y curvas de hazard por cohorte.",
    modulo: "nikodym.survival",
  },
  {
    key: "challenger",
    label: "Challenger ML",
    tagline: "Modelos challenger (XGBoost), tuning y explicabilidad SHAP.",
    modulo: "nikodym.ml",
  },
] as const
