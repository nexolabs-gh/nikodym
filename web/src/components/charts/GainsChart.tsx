import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { EMPTY, partitionLabel } from "@/lib/results-format"
import type { GainsSeries } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  BRAND,
  GRID_STROKE,
  isPrimaryPartition,
  partitionColor,
} from "./chart-theme"

/** Ítem que Recharts inyecta al tooltip de la curva. */
interface GainsTooltipProps {
  active?: boolean
  label?: number | string
  payload?: ReadonlyArray<{
    name?: string
    value?: number
    color?: string
    dataKey?: string | number
  }>
}

/** Porcentaje a 1 decimal (la ganancia acumulada es una proporción 0–1). */
function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

/** Tooltip dedicado: decil (u origen) + ganancia por serie en %, incluida la diagonal. */
function GainsTooltip({ active, label, payload }: GainsTooltipProps) {
  if (!active || !payload || payload.length === 0) return null
  const decile = typeof label === "number" ? label : Number(label)
  return (
    <div className="rounded-lg bg-secondary px-3 py-2 text-xs shadow-card ring-1 ring-foreground/10">
      <p className="mb-1.5 font-medium text-foreground">
        {decile === 0 ? "Origen" : `Decil ${decile}`}
      </p>
      <ul className="space-y-1">
        {payload.map((item, i) => (
          <li
            key={String(item.dataKey ?? item.name ?? i)}
            className="flex items-center gap-2"
          >
            <span
              className="size-2 shrink-0 rounded-[2px]"
              style={{ backgroundColor: item.color ?? "var(--brand-gray)" }}
              aria-hidden="true"
            />
            <span className="text-muted-foreground">{item.name}</span>
            <span className="ml-auto pl-3 font-mono tabular-nums text-foreground">
              {typeof item.value === "number" ? pct(item.value) : EMPTY}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Curva de ganancias (gains): ganancia acumulada `cum_bad_capture_rate` (Y, 0–100%) por
 * decil (X, 1 = 10% más riesgoso), una línea por partición —desarrollo DESTACADO, holdout/
 * oot tenues— sobre la diagonal punteada del modelo aleatorio (decil k → k/N). Cuanto más
 * arriba de la diagonal, mejor discrimina. Solo grafica lo que trae `performance.deciles`
 * (más las referencias de lectura origen/diagonal); CERO cálculo de dominio.
 */
export function GainsChart({ series }: { series: GainsSeries }) {
  const { partitions, data } = series
  if (partitions.length === 0 || data.length === 0) return null

  const maxDecile = data[data.length - 1]?.decile ?? 10
  const ticks = Array.from({ length: maxDecile + 1 }, (_, i) => i)

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 16, right: 16, bottom: 4, left: -4 }}>
          <CartesianGrid horizontal vertical={false} stroke={GRID_STROKE} />
          <XAxis
            type="number"
            dataKey="decile"
            domain={[0, maxDecile]}
            ticks={ticks}
            tickLine={false}
            axisLine={AXIS_LINE}
            tick={AXIS_TICK}
          />
          <YAxis
            domain={[0, 1]}
            ticks={[0, 0.25, 0.5, 0.75, 1]}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            tickLine={false}
            axisLine={false}
            tick={AXIS_TICK}
            width={44}
          />
          <Tooltip content={<GainsTooltip />} />
          <Legend
            verticalAlign="top"
            align="right"
            iconType="plainline"
            iconSize={14}
            wrapperStyle={{ fontSize: "0.72rem", paddingBottom: 8 }}
          />
          {partitions.map((p) => {
            const primary = isPrimaryPartition(p)
            return (
              <Line
                key={p}
                type="monotone"
                dataKey={p}
                name={partitionLabel(p)}
                stroke={partitionColor(p)}
                strokeWidth={primary ? 2.5 : 1.5}
                strokeOpacity={primary ? 1 : 0.6}
                dot={false}
                activeDot={{ r: primary ? 4 : 3 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            )
          })}
          {/* Diagonal del modelo aleatorio: referencia punteada tenue (no dato del backend). */}
          <Line
            type="linear"
            dataKey="random"
            name="Aleatorio"
            stroke={BRAND.gray}
            strokeWidth={1.5}
            strokeDasharray="5 4"
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
