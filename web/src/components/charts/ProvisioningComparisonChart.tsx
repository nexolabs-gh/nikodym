import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { formatClp, formatClpCompact } from "@/lib/results-format"
import type { ProvisioningBar } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  CURSOR_FILL,
  GRID_STROKE,
  provisioningBarColor,
} from "./chart-theme"

/** Ítem que Recharts inyecta al tooltip (el datum vive en `.payload`). */
interface ComparisonTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: ProvisioningBar }>
}

/** Tooltip dedicado: método + monto exacto (CLP) + si es la provisión que la norma obliga. */
function ComparisonTooltip({ active, payload }: ComparisonTooltipProps) {
  const d = active && payload && payload.length > 0 ? payload[0]?.payload : null
  if (!d) return null
  return (
    <div className="rounded-lg bg-secondary px-3 py-2 text-xs shadow-card ring-1 ring-foreground/10">
      <p className="mb-1 font-medium text-foreground">{d.label}</p>
      <p className="flex items-center gap-3 text-muted-foreground">
        <span>Provisión</span>
        <span className="ml-auto font-mono tabular-nums text-foreground">
          {formatClp(d.value)}
        </span>
      </p>
      {d.binding ? (
        <p className="mt-0.5 text-[0.7rem] text-eyebrow">
          La norma obliga a constituir este monto.
        </p>
      ) : null}
    </div>
  )
}

/** Label sobre la barra: monto compacto en millones ($697 M). */
function clpLabelFmt(v: string | number | boolean | null | undefined) {
  return typeof v === "number" ? formatClpCompact(v) : ""
}

/**
 * La regla del máximo del B-1 en tres barras (SDD-28 §3.5): método estándar (CMF), método interno
 * (PD·LGD·EAD) y la provisión REPORTADA = el mayor de los dos, que es la que la norma chilena
 * obliga a constituir. La barra que manda (`binding`) se resalta con contorno para leer de un
 * vistazo qué método fija el número final. Solo grafica los totales que el orquestador ya calculó
 * (`provisioningComparisonBars`); CERO cálculo. Guard por presencia: sin barras no renderiza.
 */
export function ProvisioningComparisonChart({
  bars,
}: {
  bars: ProvisioningBar[]
}) {
  if (bars.length === 0) return null

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={bars}
          margin={{ top: 22, right: 12, bottom: 0, left: 4 }}
          barCategoryGap="28%"
        >
          <CartesianGrid horizontal vertical={false} stroke={GRID_STROKE} />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={AXIS_LINE}
            tick={AXIS_TICK}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            tick={AXIS_TICK}
            width={64}
            tickFormatter={(v: number) => formatClpCompact(v)}
          />
          <Tooltip cursor={CURSOR_FILL} content={<ComparisonTooltip />} />
          <Bar
            dataKey="value"
            name="Provisión"
            radius={[3, 3, 0, 0]}
            maxBarSize={96}
            isAnimationActive={false}
          >
            {bars.map((b) => (
              <Cell
                key={b.key}
                fill={provisioningBarColor(b.key)}
                stroke={b.binding ? "var(--foreground)" : undefined}
                strokeWidth={b.binding ? 1.5 : 0}
              />
            ))}
            <LabelList
              dataKey="value"
              position="top"
              formatter={clpLabelFmt}
              fill={AXIS_TICK.fill}
              fontSize={10}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
