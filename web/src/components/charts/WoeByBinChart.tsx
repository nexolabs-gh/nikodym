import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { formatCount, formatMetric, formatPercent } from "@/lib/results-format"
import type { BinDetailRow } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  BAND_COLORS,
  BRAND,
  CURSOR_FILL,
  GRID_STROKE,
  niceBound,
  woeColor,
} from "./chart-theme"

/** Props que Recharts inyecta a un tick personalizado del eje (subconjunto usado). */
interface BinTickProps {
  x?: number
  y?: number
  payload?: { value?: string | number }
}

/**
 * Tick del eje X: la etiqueta del bin en monospace (como `FEATURE_TICK` del IvChart),
 * rotada para que los rangos numéricos largos ("[464805.09, 631639.47)") no se solapen.
 */
function BinAxisTick({ x, y, payload }: BinTickProps) {
  if (x === undefined || y === undefined) return null
  const label = payload?.value == null ? "" : String(payload.value)
  return (
    <text
      x={x}
      y={y}
      dy={10}
      textAnchor="end"
      transform={`rotate(-32, ${x}, ${y})`}
      fill={AXIS_TICK.fill}
      fontSize={10}
      fontFamily="var(--font-mono)"
    >
      {label}
    </text>
  )
}

/** Ítem que Recharts inyecta al tooltip (ambas series comparten el mismo datum en `.payload`). */
interface WoeTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: BinDetailRow }>
}

/** Tooltip dedicado: etiqueta del bin + WoE, tasa de default y conteo del bin. */
function WoeTooltip({ active, payload }: WoeTooltipProps) {
  const d = active && payload && payload.length > 0 ? payload[0]?.payload : null
  if (!d) return null
  return (
    <div className="rounded-lg bg-secondary px-3 py-2 text-xs shadow-card ring-1 ring-foreground/10">
      <p className="mb-1 font-mono font-medium text-foreground">
        {d.binLabel}
      </p>
      <ul className="space-y-0.5">
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>WoE</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatMetric(d.woe)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>Tasa de default</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatPercent(d.eventRate)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>Conteo</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatCount(d.count)}
          </span>
        </li>
      </ul>
    </div>
  )
}

/**
 * Curva WoE por bin de una variable (visor premium del binning). Barras = WoE por bin,
 * coloreadas por SIGNO (verde = protector/menor riesgo, rojo = mayor riesgo) reusando la
 * paleta semáforo de la app; encima, la TASA DE DEFAULT por bin como línea sobre un eje Y
 * secundario en % (ComposedChart) para leer WoE y default juntos. Solo grafica
 * `binning.tables_by_variable[var]` ya normalizado por `variableBinning`; CERO cálculo.
 * Guard por presencia: sin bins graficables no renderiza.
 */
export function WoeByBinChart({ rows }: { rows: BinDetailRow[] }) {
  if (rows.length === 0) return null

  // Dominio del WoE simétrico alrededor de 0 → la línea de 0 (protector/riesgo) queda
  // centrada, como en el forest plot. Solo escala; no altera ningún valor.
  const maxAbs = Math.max(
    0,
    ...rows.map((r) => (r.woe === null ? 0 : Math.abs(r.woe))),
  )
  const bound = niceBound(maxAbs)

  return (
    <div className="space-y-2">
      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 8, right: 16, bottom: 8, left: -6 }}
          >
            <CartesianGrid vertical={false} stroke={GRID_STROKE} />
            <XAxis
              dataKey="binLabel"
              interval={0}
              height={72}
              tickLine={false}
              axisLine={AXIS_LINE}
              tick={<BinAxisTick />}
            />
            <YAxis
              yAxisId="woe"
              domain={[-bound, bound]}
              width={48}
              tickLine={false}
              axisLine={false}
              tick={AXIS_TICK}
              tickFormatter={(v: number) => v.toFixed(2)}
            />
            <YAxis
              yAxisId="rate"
              orientation="right"
              domain={[0, "auto"]}
              width={44}
              tickLine={false}
              axisLine={false}
              tick={AXIS_TICK}
              tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            />
            <ReferenceLine
              yAxisId="woe"
              y={0}
              stroke="var(--border)"
              strokeWidth={1}
            />
            <Tooltip cursor={CURSOR_FILL} content={<WoeTooltip />} />
            <Bar
              yAxisId="woe"
              dataKey="woe"
              name="WoE"
              radius={[3, 3, 0, 0]}
              maxBarSize={48}
              isAnimationActive={false}
            >
              {rows.map((r) => (
                <Cell key={r.binLabel} fill={woeColor(r.woe)} />
              ))}
            </Bar>
            <Line
              yAxisId="rate"
              type="linear"
              dataKey="eventRate"
              name="Tasa de default"
              stroke={BRAND.cyan}
              strokeWidth={2}
              dot={{ r: 3, fill: BRAND.cyan, strokeWidth: 0 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Leyenda (accesibilidad: el significado no queda solo en el color). */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.7rem] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span
            className="size-2 rounded-[2px]"
            style={{ backgroundColor: BAND_COLORS.stable }}
            aria-hidden="true"
          />
          WoE &gt; 0 · menor riesgo
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="size-2 rounded-[2px]"
            style={{ backgroundColor: BAND_COLORS.redevelop }}
            aria-hidden="true"
          />
          WoE &lt; 0 · mayor riesgo
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="h-0.5 w-4 rounded-full"
            style={{ backgroundColor: BRAND.cyan }}
            aria-hidden="true"
          />
          tasa de default (eje derecho)
        </span>
      </div>
    </div>
  )
}
