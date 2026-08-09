import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import {
  formatClp,
  formatCount,
  formatPercent,
} from "@/lib/results-format"
import type { InternalGroupBar } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  BRAND,
  CURSOR_FILL,
  GRID_STROKE,
  PROVISIONING_COLORS,
} from "./chart-theme"

/** Ítem que Recharts inyecta al tooltip (ambas series comparten el mismo datum en `.payload`). */
interface GroupTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: InternalGroupBar }>
  method: string
}

/** Tooltip dedicado: publica sólo los factores que la forma ejecutada usa en la provisión. */
function GroupTooltip({ active, payload, method }: GroupTooltipProps) {
  const d = active && payload && payload.length > 0 ? payload[0]?.payload : null
  if (!d) return null
  const direct = method === "direct_loss_rate"
  return (
    <div className="rounded-lg bg-secondary px-3 py-2 text-xs shadow-card ring-1 ring-foreground/10">
      <p className="mb-1 font-medium text-foreground">{d.label}</p>
      <ul className="space-y-0.5">
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>Provisión</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatClp(d.provision)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>{direct ? "Tasa de pérdida" : "PD"}</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatPercent(direct ? d.expectedLossRate : d.pd, 2)}
          </span>
        </li>
        {direct ? null : (
          <li className="flex items-center gap-3 text-muted-foreground">
            <span>LGD</span>
            <span className="ml-auto font-mono tabular-nums text-foreground">
              {formatPercent(d.lgd, 1)}
            </span>
          </li>
        )}
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>Exposición</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatClp(d.exposure)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-[0.7rem] text-muted-foreground">
          <span>Operaciones</span>
          <span className="ml-auto font-mono tabular-nums text-muted-foreground">
            {formatCount(d.n)}
          </span>
        </li>
      </ul>
    </div>
  )
}

/**
 * Método interno por grupo homogéneo (SDD-28 §3.3): barras = provisión del grupo (eje izquierdo,
 * CLP), y encima la PD del grupo como línea sobre un eje Y secundario en % (ComposedChart), para
 * contrastar provisión con la tasa que la forma ejecutada publica: PD con `pd_lgd`, o tasa de pérdida
 * esperada con `direct_loss_rate`. Sólo grafica grupos ya normalizados; sin grupos no renderiza.
 */
export function InternalGroupsChart({
  rows,
  method,
}: {
  rows: InternalGroupBar[]
  method: string
}) {
  if (rows.length === 0) return null
  const direct = method === "direct_loss_rate"
  const rateKey = direct ? "expectedLossRate" : "pd"
  const rateLabel = direct ? "Tasa de pérdida" : "PD"

  return (
    <div className="space-y-2">
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 8, right: 8, bottom: 4, left: 8 }}
            barCategoryGap="24%"
          >
            <CartesianGrid vertical={false} stroke={GRID_STROKE} />
            <XAxis
              dataKey="label"
              interval={0}
              tickLine={false}
              axisLine={AXIS_LINE}
              tick={{ ...AXIS_TICK, fontSize: 9 }}
              angle={-30}
              textAnchor="end"
              height={48}
            />
            <YAxis
              yAxisId="clp"
              width={52}
              tickLine={false}
              axisLine={false}
              tick={AXIS_TICK}
              tickFormatter={(v: number) => `${Math.round(v / 1e6)}`}
            />
            <YAxis
              yAxisId="pd"
              orientation="right"
              domain={[0, "auto"]}
              width={40}
              tickLine={false}
              axisLine={false}
              tick={AXIS_TICK}
              tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            />
            <Tooltip cursor={CURSOR_FILL} content={<GroupTooltip method={method} />} />
            <Bar
              yAxisId="clp"
              dataKey="provision"
              name="Provisión"
              fill={PROVISIONING_COLORS.internal}
              radius={[3, 3, 0, 0]}
              maxBarSize={40}
              isAnimationActive={false}
            />
            <Line
              yAxisId="pd"
              type="monotone"
              dataKey={rateKey}
              name={rateLabel}
              stroke={BRAND.amber}
              strokeWidth={2}
              dot={{ r: 2.5, fill: BRAND.amber, strokeWidth: 0 }}
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
            style={{ backgroundColor: PROVISIONING_COLORS.internal }}
            aria-hidden="true"
          />
          provisión del grupo · millones CLP (eje izq.)
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="h-0.5 w-4 rounded-full"
            style={{ backgroundColor: BRAND.amber }}
            aria-hidden="true"
          />
          {rateLabel} del grupo (eje der.)
        </span>
      </div>
    </div>
  )
}
