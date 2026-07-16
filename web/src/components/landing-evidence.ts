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

/**
 * Conteos de tests de la 1.1.0, medidos con `uv run pytest --collect-only -q`:
 *   - suite completa .................. 3.755 (3.749 pasan · 6 skips = extra `pdf`/WeasyPrint)
 *   - los cuatro dominios sin interfaz . 649 (test_{markov,stress,forward,survival}_*.py; remedido
 *                                             al mover provisiones a UI en el track SDD-28)
 * Se publican DEBAJO de lo medido ("más de"): un número exacto se pudre con cada commit, y la
 * página entera se sostiene sobre que sus cifras cuadren cuando alguien las corre.
 */
export const TESTS_DOMINIOS = "600"
export const TESTS_SUITE = "3.700"

/**
 * Los seis dominios del motor, con su estado real en DOS ejes —y ninguno es "hecho / no hecho":
 *
 *   superficie: "UI"     → tiene preset, pantalla y capítulo en el informe.
 *               "Python" → hay que escribir el config a mano. Sin preset, sin pantalla, sin
 *                          capítulo en el informe, y NO existe CLI (`pyproject.toml` no declara
 *                          `[project.scripts]`).
 *   garantia:   "estable"      → contrato congelado bajo SemVer 1.x.
 *               "experimental" → el motor calcula y está cubierto por tests, pero la firma puede
 *                                cambiar dentro de la 1.x. No está certificado ni es apto para
 *                                producción por el solo hecho de existir.
 *
 * Cada tagline se verificó contra el código antes de publicarse. Lo que el motor NO hace se dice
 * en voz alta (roll rates, curvas de cosecha): esta página se lee entera o no sirve de nada.
 */
export const DOMINIOS = [
  {
    key: "scorecard",
    label: "Scorecard",
    superficie: "UI",
    garantia: "estable",
    tagline:
      "Binning WoE monotónico (OptBinning), selección por IV y VIF, logística sobre WoE, escalado " +
      "PDO/offset y calibración a la tasa objetivo, con AUC/KS/Gini y PSI/CSI. Es la superficie más " +
      "madura del paquete: la única bajo garantía SemVer 1.x.",
    modulo: "nikodym.scorecard",
  },
  {
    key: "provisioning",
    label: "Provisiones · CMF vs. método interno",
    superficie: "UI",
    garantia: "experimental",
    tagline:
      "Un cálculo, dos normas. CMF: 10 matrices normativas B-1/B-3 en aritmética Decimal (entre " +
      "ellas comercial, leasing, estudiantil, factoring, consumo v2025, vivienda PVG, avales y " +
      "contingentes con CCF), con el archivo de parámetros sellado por SHA-256. IFRS 9: " +
      "ECL = PD marginal × LGD × EAD descontada a la EIR, staging SICR con gatillos blandos, " +
      "backstops duros de mora y exención de bajo riesgo, y PD configurable point-in-time " +
      "(Vasicek) o through-the-cycle. El " +
      "orquestador compara ambos marcos y reporta el máximo. Con una precisión que casi nadie " +
      "hace: la regla del máximo del Capítulo B-1 (Circular 2.346) es entre el método estándar " +
      "y el método interno del banco — no entre CMF e IFRS 9. El Compendio (A-2, num. 5) excluye " +
      "el deterioro de NIIF 9 sobre las colocaciones.",
    modulo: "nikodym.provisioning",
  },
  {
    key: "stress",
    label: "Stress testing",
    superficie: "Python",
    garantia: "experimental",
    tagline:
      "Escenarios adversos y shocks macro propagados en escala logit, barridos deterministas de " +
      "sensibilidad y chequeo de dominancia entre escenarios. Incluye reverse stress: resuelve por " +
      "bisección la severidad mínima que cruza el umbral, y falla explícito si la métrica no es " +
      "monótona o si no converge, en vez de devolver un número cómodo.",
    modulo: "nikodym.stress",
  },
  {
    key: "markov",
    label: "Matrices de transición",
    superficie: "Python",
    garantia: "experimental",
    tagline:
      "Estimadores de cohorte y de duración, Chapman-Kolmogorov, Aalen-Johansen y term-structure " +
      "de PD. El problema de embedding no se esconde: es una política declarada en el config " +
      "(diagnose / regularize / forbid) y una matriz sin generador válido levanta error en vez de " +
      "degradar en silencio. No hace roll rates ni curvas de cosecha: eso todavía no existe.",
    modulo: "nikodym.markov",
  },
  {
    key: "forward",
    label: "Forward-looking",
    superficie: "Python",
    garantia: "experimental",
    tagline:
      "ARIMA y auto-ARIMA, VAR y VECM sobre series macro, con Ljung-Box sobre los residuos como " +
      "diagnóstico, y modelos satélite que traducen el escenario macroeconómico a PD y LGD, " +
      "escenario por escenario.",
    modulo: "nikodym.forward",
  },
  {
    key: "survival",
    label: "Survival",
    superficie: "Python",
    garantia: "experimental",
    tagline:
      "Kaplan-Meier, modelos de Cox y AFT, y hazard en tiempo discreto sobre datos censurados: " +
      "cuándo ocurre el incumplimiento, no solo con qué probabilidad.",
    modulo: "nikodym.survival",
  },
] as const

/**
 * Las salvedades que el motor declara solo, y que por eso mismo la página no puede callar: si el
 * código las publica en cada fila de resultados, esconderlas aquí sería mentir por omisión sobre
 * un producto regulatorio. Se muestran al pie de la sección del motor, no en letra chica.
 */
export const SALVEDADES = [
  {
    clave: "EAD constante",
    texto:
      "La EAD de IFRS 9 se despliega constante en el tiempo: el panel longitudinal está diferido, " +
      "y cada fila lo publica con el código FALTA-DATO-IFRS-4.",
  },
  {
    clave: "Parámetros CMF",
    texto:
      "Los parámetros normativos se transcribieron del compendio con asistencia de IA y " +
      "verificación visual. No son parámetros oficiales de la CMF ni están validados por ella: " +
      "requieren validación humana contra la norma vigente antes de cualquier uso productivo, y " +
      "quedan dos brechas FALTA-DATO abiertas (aforos y haircuts de garantías financieras; tablas " +
      "RAN 21-10).",
  },
  {
    clave: "Extras",
    texto:
      "Auto-ARIMA y los modelos de sobrevivencia viven tras extras opcionales del paquete " +
      "(pmdarima, lifelines).",
  },
] as const
