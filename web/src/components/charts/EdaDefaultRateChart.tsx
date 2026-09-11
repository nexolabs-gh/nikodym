import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { EMPTY, formatCount, formatPercent } from "@/lib/results-format"
import type { EdaRatePoint } from "@/lib/results-format"

import { AXIS_LINE, AXIS_TICK, BAR_PRIMARY, BRAND, CURSOR_FILL, GRID_STROKE } from "./chart-theme"

/** Ítem que Recharts inyecta al tooltip (el datum vive en `.payload`). */
interface RateTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: EdaRatePoint }>
}

/** Tooltip dedicado: período o cohorte, tasa, elegibles e incumplidas, y la marca de baja confianza. */
function RateTooltip({ active, payload }: RateTooltipProps) {
  const d = active && payload && payload.length > 0 ? payload[0]?.payload : null
  if (!d) return null
  return (
    <div className="rounded-lg bg-secondary px-3 py-2 text-xs shadow-card ring-1 ring-foreground/10">
      <p className="mb-1 font-medium text-foreground">{d.label}</p>
      <ul className="space-y-0.5">
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>Tasa de incumplimiento</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {d.rate === null ? EMPTY : formatPercent(d.rate, 2)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>Operaciones elegibles</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatCount(d.nEligible)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>Incumplidas</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatCount(d.nBad)}
          </span>
        </li>
      </ul>
      {d.lowConfidence ? (
        <p className="mt-1 text-[0.68rem] text-amber-200/90">
          Poco fiable: menos operaciones que el mínimo configurado.
        </p>
      ) : null}
    </div>
  )
}

/** Color de un punto o barra: los períodos poco fiables se pintan tenues, no se esconden. */
function pointColor(point: EdaRatePoint): string {
  return point.lowConfidence ? BRAND.gray : BAR_PRIMARY
}

/**
 * La tasa de incumplimiento en el tiempo (D-SC-5): LÍNEA sobre un eje con orden cronológico
 * (`axis="period"`) y BARRAS sobre cohortes, decidido por el eje EFECTIVO de la card y no por el
 * config — con la inferencia de D-SC-3 pueden diferir—. Sólo grafica `eda.default_rate` ya
 * normalizado por `edaRatePoints`; CERO cálculo. Los períodos de baja confianza se pintan tenues
 * y lo dicen en el tooltip: se ven, marcados, como en la tabla del motor.
 */
export function EdaDefaultRateChart({
  kind,
  points,
}: {
  kind: "line" | "bar"
  points: EdaRatePoint[]
}) {
  if (points.length === 0) return null
  const data = points.map((p) => ({ ...p, rateOrNull: p.rate ?? undefined }))

  return (
    <div className="space-y-2" data-eda-chart={kind}>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {kind === "line" ? (
            <ComposedChart data={data} margin={{ top: 12, right: 12, bottom: 4, left: 4 }}>
              <CartesianGrid horizontal vertical={false} stroke={GRID_STROKE} />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={AXIS_LINE}
                tick={AXIS_TICK}
                height={24}
              />
              <YAxis
                width={56}
                tickLine={false}
                axisLine={false}
                tick={AXIS_TICK}
                tickFormatter={(v: number) => formatPercent(v, 0)}
              />
              <Tooltip content={<RateTooltip />} />
              <Line
                type="monotone"
                dataKey="rateOrNull"
                name="Tasa de incumplimiento"
                stroke={BAR_PRIMARY}
                strokeWidth={2}
                connectNulls={false}
                dot={(props: { cx?: number; cy?: number; payload?: EdaRatePoint }) => (
                  <circle
                    key={props.payload?.key}
                    cx={props.cx}
                    cy={props.cy}
                    r={3.5}
                    fill={props.payload ? pointColor(props.payload) : BAR_PRIMARY}
                    strokeWidth={0}
                  />
                )}
                isAnimationActive={false}
              />
            </ComposedChart>
          ) : (
            <BarChart
              data={data}
              margin={{ top: 12, right: 12, bottom: 4, left: 4 }}
              barCategoryGap="28%"
            >
              <CartesianGrid horizontal vertical={false} stroke={GRID_STROKE} />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={AXIS_LINE}
                tick={AXIS_TICK}
                height={24}
              />
              <YAxis
                width={56}
                tickLine={false}
                axisLine={false}
                tick={AXIS_TICK}
                tickFormatter={(v: number) => formatPercent(v, 0)}
              />
              <Tooltip content={<RateTooltip />} cursor={CURSOR_FILL} />
              <Bar
                dataKey="rateOrNull"
                name="Tasa de incumplimiento"
                radius={[4, 4, 0, 0]}
                isAnimationActive={false}
              >
                {data.map((point) => (
                  <Cell key={point.key} fill={pointColor(point)} />
                ))}
              </Bar>
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>

      {/* Leyenda (accesibilidad: el significado no queda solo en el color). */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.7rem] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span
            className="size-2 rounded-[2px]"
            style={{ backgroundColor: BAR_PRIMARY }}
            aria-hidden="true"
          />
          {kind === "line" ? "Tasa por período" : "Tasa por cohorte"}
        </span>
        {points.some((p) => p.lowConfidence) ? (
          <span className="flex items-center gap-1.5">
            <span
              className="size-2 rounded-[2px]"
              style={{ backgroundColor: BRAND.gray }}
              aria-hidden="true"
            />
            Poco fiable (menos operaciones que el mínimo)
          </span>
        ) : null}
      </div>
    </div>
  )
}
