import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { LiftRow } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  CURSOR_FILL,
  GRID_STROKE,
  niceBound,
  partitionColor,
} from "./chart-theme"

/** Ítem que Recharts inyecta al tooltip (el datum vive en `.payload`). */
interface LiftTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: LiftRow }>
}

/** Tooltip dedicado: decil + lift (2 dec) + tasa de malos del decil + N. */
function LiftTooltip({ active, payload }: LiftTooltipProps) {
  const d = active && payload && payload.length > 0 ? payload[0]?.payload : null
  if (!d) return null
  return (
    <div className="rounded-lg bg-brand-panel-raised px-3 py-2 text-xs shadow-card ring-1 ring-white/10">
      <p className="mb-1 font-medium text-brand-offwhite">Decil {d.decile}</p>
      <p className="text-brand-placeholder">
        Lift{" "}
        <span className="ml-1 font-mono tabular-nums text-brand-offwhite">
          {d.lift.toFixed(2)}×
        </span>
      </p>
      <p className="mt-0.5 text-brand-placeholder">
        Tasa de malos{" "}
        <span className="ml-1 font-mono tabular-nums text-brand-offwhite">
          {(d.bad_rate * 100).toFixed(1)}%
        </span>
      </p>
      <p className="mt-0.5 text-[0.7rem] text-brand-gray">
        n = {d.n_total.toLocaleString("en-US")}
      </p>
    </div>
  )
}

/** Label sobre la barra (lift a 2 decimales con ×). */
function liftLabelFmt(v: string | number | boolean | null | undefined) {
  return typeof v === "number" ? `${v.toFixed(2)}×` : ""
}

/**
 * Lift por decil de una partición: barras del `lift` por decil (X, 1 = 10% más riesgoso),
 * con la línea de referencia lift = 1 (azar) siempre visible para leer "cuántas veces más
 * concentra malos que la media". Solo grafica `performance.deciles`; CERO cálculo.
 */
export function LiftChart({
  rows,
  partition,
}: {
  rows: LiftRow[]
  partition: string
}) {
  if (rows.length === 0) return null

  const maxLift = Math.max(1, ...rows.map((r) => r.lift))
  const domainTop = niceBound(maxLift)

  return (
    <div className="h-60 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={rows}
          margin={{ top: 18, right: 12, bottom: 0, left: -6 }}
          barCategoryGap="24%"
        >
          <CartesianGrid horizontal vertical={false} stroke={GRID_STROKE} />
          <XAxis
            dataKey="decile"
            tickLine={false}
            axisLine={AXIS_LINE}
            tick={AXIS_TICK}
          />
          <YAxis
            domain={[0, domainTop]}
            tickLine={false}
            axisLine={false}
            tick={AXIS_TICK}
            width={40}
          />
          <ReferenceLine
            y={1}
            stroke="rgba(255,255,255,0.35)"
            strokeDasharray="5 4"
            label={{
              value: "azar (1.0×)",
              position: "insideTopRight",
              fill: AXIS_TICK.fill,
              fontSize: 9,
            }}
          />
          <Tooltip cursor={CURSOR_FILL} content={<LiftTooltip />} />
          <Bar
            dataKey="lift"
            name="Lift"
            fill={partitionColor(partition)}
            radius={[3, 3, 0, 0]}
            maxBarSize={48}
            isAnimationActive={false}
          >
            <LabelList
              dataKey="lift"
              position="top"
              formatter={liftLabelFmt}
              fill={AXIS_TICK.fill}
              fontSize={9}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
