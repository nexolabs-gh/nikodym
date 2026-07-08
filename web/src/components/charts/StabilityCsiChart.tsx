import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { CsiBarRow } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  BRAND,
  CURSOR_FILL,
  GRID_STROKE,
  bandColor,
  bandLabel,
  niceBound,
} from "./chart-theme"

/** Tick de variable en monospace (como se listan las features en la app). */
const FEATURE_TICK = { ...AXIS_TICK, fontFamily: "var(--font-mono)" }

/** Ítem que Recharts inyecta al tooltip (el datum vive en `.payload`). */
interface CsiTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: CsiBarRow }>
}

/** Tooltip dedicado: variable + CSI (4 decimales) + banda con su color. */
function CsiTooltip({ active, payload }: CsiTooltipProps) {
  const d = active && payload && payload.length > 0 ? payload[0]?.payload : null
  if (!d) return null
  return (
    <div className="rounded-lg bg-brand-panel-raised px-3 py-2 text-xs shadow-card ring-1 ring-white/10">
      <p className="mb-1 font-mono font-medium text-brand-offwhite">
        {d.feature}
      </p>
      <p className="text-brand-placeholder">
        CSI{" "}
        <span className="ml-1 font-mono tabular-nums text-brand-offwhite">
          {d.value === null ? "—" : d.value.toFixed(4)}
        </span>
      </p>
      <p className="mt-1 flex items-center gap-1.5 text-[0.7rem]">
        <span
          className="size-2 rounded-full"
          style={{ backgroundColor: bandColor(d.band) }}
          aria-hidden="true"
        />
        <span className="text-brand-placeholder">{bandLabel(d.band)}</span>
      </p>
    </div>
  )
}

/** Label al final de la barra (3 decimales; el tooltip da los 4). Omite nulos. */
function csiLabelFmt(v: string | number | boolean | null | undefined) {
  return typeof v === "number" ? v.toFixed(3) : ""
}

/**
 * CSI por característica: barras horizontales ordenadas de mayor a menor (orden ya resuelto
 * por `csiBars`), coloreadas por banda, con la peor característica (`worst`) resaltada con
 * un contorno claro y las líneas de umbral estable/revisar como referencia de escala. Solo
 * grafica `stability_metrics`; CERO cálculo.
 */
export function StabilityCsiChart({
  rows,
  worst,
  stableThreshold,
  reviewThreshold,
}: {
  rows: CsiBarRow[]
  worst?: string | null
  stableThreshold: number
  reviewThreshold: number
}) {
  if (rows.length === 0) return null

  // Alto proporcional al número de variables (evita barras aplastadas o estiradas).
  const height = Math.max(120, rows.length * 40 + 24)
  const maxValue = Math.max(
    0,
    ...rows.map((r) => (r.value === null ? 0 : r.value)),
  )
  const domainTop = niceBound(Math.max(reviewThreshold, maxValue))

  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={rows}
          layout="vertical"
          margin={{ top: 16, right: 56, bottom: 4, left: 8 }}
          barCategoryGap="28%"
        >
          <CartesianGrid horizontal={false} vertical stroke={GRID_STROKE} />
          <XAxis
            type="number"
            domain={[0, domainTop]}
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
          <ReferenceLine
            x={stableThreshold}
            stroke="rgba(52,211,153,0.5)"
            strokeDasharray="4 3"
            label={{
              value: `estable ≤${stableThreshold.toFixed(2)}`,
              position: "insideTopRight",
              fill: AXIS_TICK.fill,
              fontSize: 9,
            }}
          />
          <ReferenceLine
            x={reviewThreshold}
            stroke="rgba(248,113,113,0.5)"
            strokeDasharray="4 3"
            label={{
              value: `revisar ≤${reviewThreshold.toFixed(2)}`,
              position: "insideTopRight",
              fill: AXIS_TICK.fill,
              fontSize: 9,
            }}
          />
          <Tooltip cursor={CURSOR_FILL} content={<CsiTooltip />} />
          <Bar
            dataKey="value"
            name="CSI"
            radius={[0, 3, 3, 0]}
            maxBarSize={26}
            isAnimationActive={false}
          >
            {rows.map((r) => {
              const isWorst = worst != null && r.feature === worst
              return (
                <Cell
                  key={r.feature}
                  fill={bandColor(r.band)}
                  stroke={isWorst ? BRAND.offwhite : undefined}
                  strokeWidth={isWorst ? 1.5 : undefined}
                />
              )
            })}
            <LabelList
              dataKey="value"
              position="right"
              formatter={csiLabelFmt}
              fill={AXIS_TICK.fill}
              fontSize={10}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
