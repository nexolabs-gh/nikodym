/**
 * Tema compartido de los visores premium (Recharts). Deriva de los tokens de marca
 * (`web/src/styles/tokens.css`) para que los charts NO usen los defaults baratos de
 * Recharts. Los colores se fijan en HEX a propósito: Recharts pinta SVG y necesita
 * valores concretos (no acepta `var(--brand-*)` en todas las props); si cambia la
 * marca, sincronizar este bloque con `tokens.css`. CERO lógica de dominio: solo estilo.
 */

/** HEX 1:1 con `tokens.css` (`--brand-*`). Sincronizar aquí si cambia la identidad. */
export const BRAND = {
  cyan: "#4fc3e8", // --brand-cyan
  accent: "#1a46b0", // --brand-accent
  accentDark: "#2e6ff2", // --brand-accent-dark
  placeholder: "#9fb0c6", // --brand-placeholder
  gray: "#5e708a", // --brand-gray
  offwhite: "#f4f7fc", // --brand-offwhite
  panelRaised: "#0d2547", // --brand-panel-raised
  /** Señal de alerta, en el mismo espíritu que el `amber-200/90` que ya usa la app. */
  amber: "#fcd34d",
} as const

/**
 * Paleta categórica de las métricas de discriminación. MISMO color = MISMA métrica en
 * todos los charts. Accesibilidad: el color NUNCA es el único distintivo — siempre se
 * acompaña de leyenda, labels y ejes textuales.
 */
export const METRIC_COLORS = {
  auc: BRAND.cyan,
  gini: BRAND.accentDark,
  ks: BRAND.placeholder,
} as const

/** Color primario de barras de una sola serie (IV, histograma). */
export const BAR_PRIMARY = BRAND.accentDark

/**
 * Paleta por partición (gains/lift): desarrollo DESTACADO (cyan brillante), holdout/oot
 * TENUES (azul medio / gris), para leer "desarrollo vs el resto" de un vistazo. MISMO
 * color = MISMA partición. Accesibilidad: el color nunca es el único distintivo (leyenda
 * + labels de eje textuales acompañan siempre).
 */
export const PARTITION_COLORS: Record<string, string> = {
  desarrollo: BRAND.cyan,
  holdout: BRAND.accentDark,
  oot: BRAND.gray,
} as const

/** Color de una partición; fallback neutro para una partición no prevista (robustez). */
export function partitionColor(partition: string): string {
  return PARTITION_COLORS[partition] ?? BRAND.placeholder
}

/** ¿Es la partición la principal (desarrollo)? Decide el resalte visual en los charts. */
export function isPrimaryPartition(partition: string): boolean {
  return partition === "desarrollo"
}

/**
 * Paleta SEMÁNTICA de bandas de estabilidad (PSI/CSI), tipo semáforo sobre navy:
 * estable=verde (ok), revisar=ámbar (vigilar), redesarrollar=rojo (alerta), no
 * evaluable=gris neutro. Los verdes/rojos usan las variantes -400 de Tailwind, que
 * respiran mejor sobre el fondo oscuro (mismo espíritu suave que el `amber-200/90`
 * de la app). Accesibilidad: SIEMPRE acompañadas de etiqueta (`BAND_LABELS`), nunca
 * el color como único distintivo. Etiquetas en español (SDD-11: banda→acción).
 */
export const BAND_COLORS: Record<string, string> = {
  stable: "#34d399", // emerald-400 → estable / ok
  review: BRAND.amber, // ámbar → revisar / vigilar
  redevelop: "#f87171", // red-400 → redesarrollar / alerta
  not_evaluable: BRAND.gray, // gris neutro → sin valor comparable
} as const

/** Etiqueta humana de cada banda (leyenda accesible). */
export const BAND_LABELS: Record<string, string> = {
  stable: "Estable",
  review: "Revisar",
  redevelop: "Redesarrollar",
  not_evaluable: "No evaluable",
} as const

/** Color de una banda; fallback neutro para un valor de enum no previsto (robustez). */
export function bandColor(band: string): string {
  return BAND_COLORS[band] ?? BRAND.gray
}

/** Etiqueta de una banda; fallback al propio slug si el enum crece (no oculta nada). */
export function bandLabel(band: string): string {
  return BAND_LABELS[band] ?? band
}

/**
 * Color del punto/barra del forest plot según si el signo del coeficiente es el
 * esperado por el backend (`sign_ok`). No recalcula nada: solo mapea el flag a color.
 */
export function coefColor(signOk: boolean | null | undefined): string {
  if (signOk === false) return BRAND.amber // signo inesperado → alerta
  return BRAND.cyan // esperado, o no evaluable
}

/**
 * Color de una barra WoE según su SIGNO (no recalcula nada; solo mapea el signo ya
 * materializado a un token de marca). WoE>0 = bin protector (menor riesgo) → verde
 * "estable"; WoE<0 = mayor riesgo → rojo "redesarrollar"; 0/`null` (p.ej. Totals) → gris
 * neutro. Reutiliza la paleta semáforo de `BAND_COLORS` (no introduce HEX nuevos).
 * Accesibilidad: el color nunca es el único distintivo — eje, tabla y tooltip dan el número.
 */
export function woeColor(woe: number | null | undefined): string {
  if (woe === null || woe === undefined || !Number.isFinite(woe) || woe === 0) {
    return BRAND.gray
  }
  return woe > 0 ? BAND_COLORS.stable : BAND_COLORS.redevelop
}

/** Props comunes de ejes: tenues, tipografía chica, sin líneas pesadas. */
export const AXIS_TICK = { fill: BRAND.placeholder, fontSize: 11 }
export const AXIS_LINE = { stroke: "rgba(255,255,255,0.14)" }

/** Grid muy tenue (solo el eje que aporta, nunca una retícula pesada). */
export const GRID_STROKE = "rgba(255,255,255,0.06)"

/** Resalte del cursor del tooltip (velo mínimo, no el bloque gris default). */
export const CURSOR_FILL = { fill: "rgba(255,255,255,0.04)" }

/** Redondea una cota a un valor "bonito" para dominios simétricos del forest plot. */
export function niceBound(maxAbs: number): number {
  if (!Number.isFinite(maxAbs) || maxAbs <= 0) return 1
  const pow = 10 ** Math.floor(Math.log10(maxAbs))
  const scaled = maxAbs / pow
  const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10
  return step * pow
}
