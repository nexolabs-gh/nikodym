import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { IvRow } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  BAR_PRIMARY,
  CURSOR_FILL,
  GRID_STROKE,
} from "./chart-theme"
import { ChartTooltip } from "./ChartTooltip"

/** Tick de variable en monospace (calza con cómo se listan las features en la app). */
const FEATURE_TICK = { ...AXIS_TICK, fontFamily: "var(--font-mono)" }

/** Label al final de la barra (IV a 4 decimales, como la tabla original). */
function ivLabelFmt(v: string | number | boolean | null | undefined) {
  return typeof v === "number" ? v.toFixed(4) : ""
}

/**
 * IV por variable: barras horizontales ordenadas de mayor a menor (el orden llega ya
 * resuelto desde `sortByIv`). Solo grafica `binning.iv_by_variable`; CERO cálculo.
 */
export function IvChart({ rows }: { rows: IvRow[] }) {
  // Alto proporcional al número de variables (evita barras aplastadas o estiradas).
  const height = Math.max(120, rows.length * 40 + 16)
  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={rows}
          layout="vertical"
          margin={{ top: 4, right: 56, bottom: 4, left: 8 }}
          barCategoryGap="28%"
        >
          <CartesianGrid horizontal={false} vertical stroke={GRID_STROKE} />
          <XAxis
            type="number"
            tickLine={false}
            axisLine={false}
            tick={AXIS_TICK}
          />
          <YAxis
            type="category"
            dataKey="feature"
            width={140}
            tickLine={false}
            axisLine={AXIS_LINE}
            tick={FEATURE_TICK}
          />
          <Tooltip
            cursor={CURSOR_FILL}
            content={<ChartTooltip formatValue={(v) => v.toFixed(4)} />}
          />
          <Bar
            dataKey="iv"
            name="IV"
            fill={BAR_PRIMARY}
            radius={[0, 3, 3, 0]}
            maxBarSize={26}
            isAnimationActive={false}
          >
            <LabelList
              dataKey="iv"
              position="right"
              formatter={ivLabelFmt}
              fill={AXIS_TICK.fill}
              fontSize={10}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
