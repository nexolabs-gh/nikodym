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

import type { PsiBarRow } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  CURSOR_FILL,
  GRID_STROKE,
  bandColor,
  bandLabel,
  niceBound,
} from "./chart-theme"

/** Ítem que Recharts inyecta al tooltip (el datum vive en `.payload`). */
interface PsiTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: PsiBarRow }>
}

/** Tooltip dedicado: comparación + valor PSI (4 decimales) + banda con su color. */
function PsiTooltip({ active, payload }: PsiTooltipProps) {
  const d = active && payload && payload.length > 0 ? payload[0]?.payload : null
  if (!d) return null
  return (
    <div className="rounded-lg bg-secondary px-3 py-2 text-xs shadow-card ring-1 ring-foreground/10">
      <p className="mb-1 font-medium text-foreground">{d.label}</p>
      <p className="text-muted-foreground">
        PSI{" "}
        <span className="ml-1 font-mono tabular-nums text-foreground">
          {d.value === null ? "—" : d.value.toFixed(4)}
        </span>
      </p>
      <p className="mt-1 flex items-center gap-1.5 text-[0.7rem]">
        <span
          className="size-2 rounded-full"
          style={{ backgroundColor: bandColor(d.band) }}
          aria-hidden="true"
        />
        <span className="text-muted-foreground">{bandLabel(d.band)}</span>
      </p>
    </div>
  )
}

/** Label sobre la barra (3 decimales; el tooltip da los 4). Omite nulos. */
function psiLabelFmt(v: string | number | boolean | null | undefined) {
  return typeof v === "number" ? v.toFixed(3) : ""
}

/**
 * PSI por comparación (una barra por comparación, coloreada por su banda de estabilidad)
 * con las líneas de umbral estable/revisar dibujadas para dar CONTEXTO DE ESCALA: aunque
 * el PSI real sea diminuto (≈0.01), los umbrales 0.10/0.25 quedan visibles y se lee "muy
 * por debajo del límite". Solo grafica lo que trae `stability_metrics`; CERO cálculo.
 */
export function PsiByComparisonChart({
  rows,
  stableThreshold,
  reviewThreshold,
}: {
  rows: PsiBarRow[]
  stableThreshold: number
  reviewThreshold: number
}) {
  if (rows.length === 0) return null

  // Tope del eje: incluye SIEMPRE el umbral de revisar (para que ambas líneas se vean) y
  // el PSI mayor si llegara a superarlo (banda review/redevelop). `niceBound` lo redondea.
  const maxValue = Math.max(
    0,
    ...rows.map((r) => (r.value === null ? 0 : r.value)),
  )
  const domainTop = niceBound(Math.max(reviewThreshold, maxValue))

  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={rows}
          margin={{ top: 18, right: 12, bottom: 0, left: -6 }}
          barCategoryGap="34%"
        >
          <CartesianGrid horizontal vertical={false} stroke={GRID_STROKE} />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={AXIS_LINE}
            tick={AXIS_TICK}
          />
          <YAxis
            domain={[0, domainTop]}
            tickLine={false}
            axisLine={false}
            tick={AXIS_TICK}
            width={44}
          />
          <ReferenceLine
            y={stableThreshold}
            stroke="rgba(52,211,153,0.5)"
            strokeDasharray="4 3"
            label={{
              value: `estable ≤${stableThreshold.toFixed(2)}`,
              position: "insideTopLeft",
              fill: AXIS_TICK.fill,
              fontSize: 9,
            }}
          />
          <ReferenceLine
            y={reviewThreshold}
            stroke="rgba(248,113,113,0.5)"
            strokeDasharray="4 3"
            label={{
              value: `revisar ≤${reviewThreshold.toFixed(2)}`,
              position: "insideTopLeft",
              fill: AXIS_TICK.fill,
              fontSize: 9,
            }}
          />
          <Tooltip cursor={CURSOR_FILL} content={<PsiTooltip />} />
          <Bar
            dataKey="value"
            name="PSI"
            radius={[3, 3, 0, 0]}
            maxBarSize={56}
            isAnimationActive={false}
          >
            {rows.map((r) => (
              <Cell key={r.comparison} fill={bandColor(r.band)} />
            ))}
            <LabelList
              dataKey="value"
              position="top"
              formatter={psiLabelFmt}
              fill={AXIS_TICK.fill}
              fontSize={10}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
