import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { MetricRow } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  CURSOR_FILL,
  GRID_STROKE,
  METRIC_COLORS,
} from "./chart-theme"
import { ChartTooltip } from "./ChartTooltip"

/** Series graficadas: MISMO color = MISMA métrica en toda la app (ver chart-theme). */
const SERIES = [
  { key: "auc", name: "AUC", color: METRIC_COLORS.auc },
  { key: "gini", name: "Gini", color: METRIC_COLORS.gini },
  { key: "ks", name: "KS", color: METRIC_COLORS.ks },
] as const

/** Label compacto sobre cada barra (2 decimales; el tooltip da los 4). */
function labelFmt(v: string | number | boolean | null | undefined) {
  return typeof v === "number" ? v.toFixed(2) : ""
}

/**
 * Discriminación: barras agrupadas AUC/Gini/KS por partición, en escala honesta 0–1.
 * Solo grafica los máximos que el backend ya materializó (`performance`); CERO cálculo.
 */
export function DiscriminationChart({ rows }: { rows: MetricRow[] }) {
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={rows}
          margin={{ top: 18, right: 8, bottom: 0, left: -8 }}
          barCategoryGap="26%"
          barGap={3}
        >
          <CartesianGrid horizontal vertical={false} stroke={GRID_STROKE} />
          <XAxis
            dataKey="partition"
            tickLine={false}
            axisLine={AXIS_LINE}
            tick={AXIS_TICK}
          />
          <YAxis
            domain={[0, 1]}
            ticks={[0, 0.25, 0.5, 0.75, 1]}
            tickLine={false}
            axisLine={false}
            tick={AXIS_TICK}
            width={40}
          />
          <Tooltip cursor={CURSOR_FILL} content={<ChartTooltip />} />
          <Legend
            verticalAlign="top"
            align="right"
            iconType="circle"
            iconSize={8}
            wrapperStyle={{ fontSize: "0.72rem", paddingBottom: 8 }}
          />
          {SERIES.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.name}
              fill={s.color}
              radius={[3, 3, 0, 0]}
              maxBarSize={40}
              isAnimationActive={false}
            >
              <LabelList
                dataKey={s.key}
                position="top"
                formatter={labelFmt}
                fill={AXIS_TICK.fill}
                fontSize={9}
              />
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
