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

/** Color primario de barras de una sola serie (IV). */
export const BAR_PRIMARY = BRAND.accentDark

/**
 * Color del punto/barra del forest plot según si el signo del coeficiente es el
 * esperado por el backend (`sign_ok`). No recalcula nada: solo mapea el flag a color.
 */
export function coefColor(signOk: boolean | null | undefined): string {
  if (signOk === false) return BRAND.amber // signo inesperado → alerta
  return BRAND.cyan // esperado, o no evaluable
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
