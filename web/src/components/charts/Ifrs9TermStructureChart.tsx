import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import {
  EMPTY,
  formatMoney,
  formatMoneyCompact,
  formatPercent,
} from "@/lib/results-format"
import type { Ifrs9TermPoint } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  GRID_STROKE,
  IFRS9_COLORS,
} from "./chart-theme"

/** Ítem que Recharts inyecta al tooltip (ambas series comparten el datum en `.payload`). */
interface TermTooltipProps {
  active?: boolean
  label?: number | string
  payload?: ReadonlyArray<{ payload?: Ifrs9TermPoint }>
}

/** Tooltip dedicado: período + ECL marginal/acumulada (agnóstico de moneda), PD marginal y descuento. */
function TermTooltip({ active, label, payload }: TermTooltipProps) {
  const d = active && payload && payload.length > 0 ? payload[0]?.payload : null
  if (!d) return null
  const period = typeof label === "number" ? label : Number(label)
  return (
    <div className="rounded-lg bg-secondary px-3 py-2 text-xs shadow-card ring-1 ring-foreground/10">
      <p className="mb-1 font-medium text-foreground">
        {Number.isFinite(period) ? `Período ${period}` : EMPTY}
      </p>
      <ul className="space-y-0.5">
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>ECL marginal</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatMoney(d.marginal)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>ECL acumulada</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatMoney(d.cumulative)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>PD marginal</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatPercent(d.pdWeighted, 2)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-[0.7rem] text-muted-foreground">
          <span>Factor de descuento</span>
          <span className="ml-auto font-mono tabular-nums text-muted-foreground">
            {formatPercent(d.discount, 1)}
          </span>
        </li>
      </ul>
      <p className="mt-1 text-[0.68rem] text-muted-foreground">
        Runoff lifetime — no es la ECL reportada.
      </p>
    </div>
  )
}

/**
 * Curva de ECL LIFETIME (SDD-16): el runoff de la pérdida esperada de la cartera período a período.
 * Área = ECL marginal (la pérdida del período); línea = ECL acumulada. Montos AGNÓSTICOS de moneda.
 *
 * HONESTIDAD (público = un banco): esta curva NO es la provisión reportada. Es la FORMA del riesgo
 * en el tiempo, asumiendo EAD constante (FALTA-DATO-IFRS-4); su acumulada del último período NO
 * iguala `total_ecl_reported` (que trunca por stage). El rótulo lo deja explícito en el título,
 * la leyenda y el tooltip. Solo grafica `ecl_term_structure` ya normalizado por `ifrs9TermStructure`;
 * CERO cálculo. Guard por presencia: sin puntos no renderiza.
 */
export function Ifrs9TermStructureChart({ points }: { points: Ifrs9TermPoint[] }) {
  if (points.length === 0) return null

  return (
    <div className="space-y-2">
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={points}
            margin={{ top: 12, right: 12, bottom: 4, left: 4 }}
          >
            <defs>
              <linearGradient id="ifrs9-ecl-marginal" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={IFRS9_COLORS.ecl} stopOpacity={0.35} />
                <stop offset="100%" stopColor={IFRS9_COLORS.ecl} stopOpacity={0.04} />
              </linearGradient>
            </defs>
            <CartesianGrid horizontal vertical={false} stroke={GRID_STROKE} />
            <XAxis
              dataKey="period"
              tickLine={false}
              axisLine={AXIS_LINE}
              tick={AXIS_TICK}
              tickFormatter={(v: number) => `P${v}`}
              height={24}
            />
            <YAxis
              width={56}
              tickLine={false}
              axisLine={false}
              tick={AXIS_TICK}
              tickFormatter={(v: number) => formatMoneyCompact(v)}
            />
            <Tooltip content={<TermTooltip />} />
            <Area
              type="monotone"
              dataKey="marginal"
              name="ECL marginal"
              stroke={IFRS9_COLORS.ecl}
              strokeWidth={2}
              fill="url(#ifrs9-ecl-marginal)"
              dot={{ r: 2.5, fill: IFRS9_COLORS.ecl, strokeWidth: 0 }}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="cumulative"
              name="ECL acumulada"
              stroke={IFRS9_COLORS.eclCumulative}
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={{ r: 2.5, fill: IFRS9_COLORS.eclCumulative, strokeWidth: 0 }}
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
            style={{ backgroundColor: IFRS9_COLORS.ecl }}
            aria-hidden="true"
          />
          ECL marginal por período
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="h-0.5 w-4 rounded-full"
            style={{ backgroundColor: IFRS9_COLORS.eclCumulative }}
            aria-hidden="true"
          />
          ECL acumulada (runoff lifetime)
        </span>
      </div>
    </div>
  )
}
