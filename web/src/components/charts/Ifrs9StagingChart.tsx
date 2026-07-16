import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import {
  formatCount,
  formatMoney,
  formatPercent,
} from "@/lib/results-format"
import type { Ifrs9StageRow } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  CURSOR_FILL,
  GRID_STROKE,
  IFRS9_COLORS,
  ifrs9StageColor,
} from "./chart-theme"

/** Ítem que Recharts inyecta al tooltip (ambas series comparten el datum en `.payload`). */
interface StageTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: Ifrs9StageRow }>
}

/** Tooltip dedicado: stage + n operaciones, EAD, ECL y cobertura. Montos agnósticos de moneda. */
function StageTooltip({ active, payload }: StageTooltipProps) {
  const d = active && payload && payload.length > 0 ? payload[0]?.payload : null
  if (!d) return null
  return (
    <div className="rounded-lg bg-secondary px-3 py-2 text-xs shadow-card ring-1 ring-foreground/10">
      <p className="mb-1 font-medium text-foreground">{d.label}</p>
      <ul className="space-y-0.5">
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>Exposición (EAD)</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatMoney(d.ead)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>ECL reportada</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatMoney(d.ecl)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>Cobertura</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatPercent(d.coverage, 2)}
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
 * Distribución por etapa IFRS 9 (SDD-16): barras = exposición (EAD) por Stage 1/2/3 (eje izquierdo),
 * coloreadas por riesgo creciente, y encima la COBERTURA (ECL/EAD) como línea sobre un eje Y
 * secundario en % (ComposedChart), para leer "la mayor exposición vive en Stage 1, pero la cobertura
 * sube fuerte hacia Stage 3". Solo grafica `staging_distribution` ya normalizado por `ifrs9StageRows`;
 * CERO cálculo. Guard por presencia: sin filas no renderiza. Montos AGNÓSTICOS de moneda.
 */
export function Ifrs9StagingChart({ rows }: { rows: Ifrs9StageRow[] }) {
  if (rows.length === 0) return null

  return (
    <div className="space-y-2">
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 8, right: 8, bottom: 4, left: 8 }}
            barCategoryGap="28%"
          >
            <CartesianGrid vertical={false} stroke={GRID_STROKE} />
            <XAxis
              dataKey="label"
              interval={0}
              tickLine={false}
              axisLine={AXIS_LINE}
              tick={AXIS_TICK}
              height={24}
            />
            <YAxis
              yAxisId="ead"
              width={52}
              tickLine={false}
              axisLine={false}
              tick={AXIS_TICK}
              tickFormatter={(v: number) => `${Math.round(v / 1e6)}`}
            />
            <YAxis
              yAxisId="cov"
              orientation="right"
              domain={[0, "auto"]}
              width={40}
              tickLine={false}
              axisLine={false}
              tick={AXIS_TICK}
              tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            />
            <Tooltip cursor={CURSOR_FILL} content={<StageTooltip />} />
            <Bar
              yAxisId="ead"
              dataKey="ead"
              name="Exposición"
              radius={[3, 3, 0, 0]}
              maxBarSize={72}
              isAnimationActive={false}
            >
              {rows.map((r) => (
                <Cell key={r.stage} fill={ifrs9StageColor(r.stage)} />
              ))}
            </Bar>
            <Line
              yAxisId="cov"
              type="monotone"
              dataKey="coverage"
              name="Cobertura"
              stroke={IFRS9_COLORS.coverage}
              strokeWidth={2}
              dot={{ r: 3, fill: IFRS9_COLORS.coverage, strokeWidth: 0 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Leyenda (accesibilidad: el significado no queda solo en el color). */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.7rem] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="flex gap-0.5" aria-hidden="true">
            {[1, 2, 3].map((s) => (
              <span
                key={s}
                className="size-2 rounded-[2px]"
                style={{ backgroundColor: ifrs9StageColor(s) }}
              />
            ))}
          </span>
          exposición (EAD) por etapa · millones (eje izq.)
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="h-0.5 w-4 rounded-full"
            style={{ backgroundColor: IFRS9_COLORS.coverage }}
            aria-hidden="true"
          />
          cobertura ECL/EAD (eje der.)
        </span>
      </div>
    </div>
  )
}
