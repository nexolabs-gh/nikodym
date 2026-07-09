import {
  CartesianGrid,
  ErrorBar,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { formatCount, formatPercent, partitionLabel } from "@/lib/results-format"
import type { ReliabilityPoint, ReliabilityView } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  BRAND,
  GRID_STROKE,
  isPrimaryPartition,
  niceBound,
  partitionColor,
} from "./chart-theme"

/** Punto del chart: el punto normalizado + la etiqueta de su partición (para el tooltip). */
interface ReliabilityChartPoint extends ReliabilityPoint {
  partition: string
}

/** Ítem que Recharts inyecta al tooltip (el datum del bin vive en `.payload`). */
interface ReliabilityTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: ReliabilityChartPoint }>
}

/** Tooltip por punto: partición + bin, PD predicha, default observado, IC de Wilson y n. */
function ReliabilityTooltip({ active, payload }: ReliabilityTooltipProps) {
  const d = active && payload && payload.length > 0 ? payload[0]?.payload : null
  if (!d) return null
  return (
    <div className="rounded-lg bg-brand-panel-raised px-3 py-2 text-xs shadow-card ring-1 ring-white/10">
      <p className="mb-1 font-medium text-brand-offwhite">
        {d.partition} · bin {d.bin}
      </p>
      <ul className="space-y-0.5">
        <li className="flex items-center gap-3 text-brand-placeholder">
          <span>PD predicha</span>
          <span className="ml-auto font-mono tabular-nums text-brand-offwhite">
            {formatPercent(d.pred, 2)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-brand-placeholder">
          <span>Default observado</span>
          <span className="ml-auto font-mono tabular-nums text-brand-offwhite">
            {formatPercent(d.obs, 2)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-brand-placeholder">
          <span>IC Wilson 95%</span>
          <span className="ml-auto font-mono tabular-nums text-brand-offwhite">
            [{formatPercent(d.ciLow, 2)}, {formatPercent(d.ciHigh, 2)}]
          </span>
        </li>
        <li className="flex items-center gap-3 text-brand-placeholder">
          <span>n</span>
          <span className="ml-auto font-mono tabular-nums text-brand-offwhite">
            {formatCount(d.n)}
          </span>
        </li>
      </ul>
    </div>
  )
}

/**
 * Curva de confiabilidad de calibración (reliability diagram): un punto por bin en
 * (PD predicha, default observado), una serie por partición coloreada con `partitionColor`,
 * sobre la DIAGONAL y=x punteada ("calibración perfecta") que es la clave de lectura —
 * sobre la diagonal el modelo SUBESTIMA el riesgo; bajo ella lo SOBREESTIMA. Cada punto
 * lleva su banda de Wilson 95% como error bar vertical (`ci_low..ci_high`). Ambos ejes
 * comparten dominio `[0, niceBound(máx pred/obs/ci)]`. Solo grafica lo que `reliabilityCurve`
 * ya normalizó; CERO cálculo de dominio. Guard por presencia: sin puntos no renderiza.
 */
export function CalibrationReliabilityChart({
  view,
}: {
  view: ReliabilityView
}) {
  // Serie por partición: puntos enriquecidos con su etiqueta y ordenados por PD predicha
  // (para que la línea de unión sea legible). Descarta particiones sin puntos graficables.
  const series = view.partitions
    .map((p) => ({
      partition: p.partition,
      label: partitionLabel(p.partition),
      color: partitionColor(p.partition),
      primary: isPrimaryPartition(p.partition),
      points: p.points
        .map(
          (pt): ReliabilityChartPoint => ({
            ...pt,
            partition: partitionLabel(p.partition),
          }),
        )
        .sort((a, b) => a.pred - b.pred),
    }))
    .filter((s) => s.points.length > 0)

  if (series.length === 0) return null

  // Dominio común de ambos ejes: 0..cota "bonita" del máximo de predicho/observado/CI.
  const maxVal = Math.max(
    0,
    ...series.flatMap((s) =>
      s.points.map((pt) => Math.max(pt.pred, pt.obs, pt.ciHigh)),
    ),
  )
  const bound = niceBound(maxVal)
  const pctDigits = bound <= 0.1 ? 1 : 0
  const tickPct = (v: number) => formatPercent(v, pctDigits)

  return (
    <div className="space-y-2">
      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 12, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={GRID_STROKE} />
            <XAxis
              type="number"
              dataKey="pred"
              name="PD predicha"
              domain={[0, bound]}
              tickFormatter={tickPct}
              tickLine={false}
              axisLine={AXIS_LINE}
              tick={AXIS_TICK}
            />
            <YAxis
              type="number"
              dataKey="obs"
              name="Default observado"
              domain={[0, bound]}
              tickFormatter={tickPct}
              tickLine={false}
              axisLine={false}
              tick={AXIS_TICK}
              width={48}
            />
            {/* Diagonal de referencia y=x: calibración perfecta (clave de lectura del visor). */}
            <ReferenceLine
              segment={[
                { x: 0, y: 0 },
                { x: bound, y: bound },
              ]}
              stroke={BRAND.gray}
              strokeDasharray="5 4"
              strokeWidth={1.5}
              ifOverflow="hidden"
              label={{
                value: "calibración perfecta",
                position: "insideBottomRight",
                fill: BRAND.gray,
                fontSize: 9,
              }}
            />
            <Tooltip
              cursor={{ strokeDasharray: "3 3", stroke: "rgba(255,255,255,0.12)" }}
              content={<ReliabilityTooltip />}
            />
            <Legend
              verticalAlign="top"
              align="right"
              iconType="circle"
              iconSize={9}
              wrapperStyle={{ fontSize: "0.72rem", paddingBottom: 8 }}
            />
            {series.map((s) => (
              <Scatter
                key={s.partition}
                name={s.label}
                data={s.points}
                fill={s.color}
                stroke={s.color}
                line={{ strokeDasharray: s.primary ? undefined : "4 3" }}
                lineType="joint"
                isAnimationActive={false}
              >
                <ErrorBar
                  dataKey="ciError"
                  direction="y"
                  width={4}
                  strokeWidth={1.25}
                  stroke={s.color}
                />
              </Scatter>
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      {/* Notas de lectura (accesibilidad: el significado no queda solo en el color). */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.7rem] text-brand-placeholder">
        <span className="flex items-center gap-1.5">
          <span
            className="h-0 w-4 border-t border-dashed"
            style={{ borderColor: BRAND.gray }}
            aria-hidden="true"
          />
          diagonal = calibración perfecta
        </span>
        <span className="text-brand-gray">
          barra vertical = intervalo de Wilson 95%
        </span>
      </div>
    </div>
  )
}
