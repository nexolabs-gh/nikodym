import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import {
  formatClp,
  formatClpCompact,
  formatCount,
  formatPercentValue,
} from "@/lib/results-format"
import type { CmfCategoryBar } from "@/lib/results-format"

import {
  AXIS_LINE,
  AXIS_TICK,
  CURSOR_FILL,
  GRID_STROKE,
  PROVISIONING_COLORS,
} from "./chart-theme"

/** Ítem que Recharts inyecta al tooltip (el datum vive en `.payload`). */
interface CategoryTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: CmfCategoryBar }>
}

/** Tooltip dedicado: categoría + provisión (CLP), exposición, PE ponderada y nº de operaciones. */
function CategoryTooltip({ active, payload }: CategoryTooltipProps) {
  const d = active && payload && payload.length > 0 ? payload[0]?.payload : null
  if (!d) return null
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
          <span>Exposición</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatClp(d.exposure)}
          </span>
        </li>
        <li className="flex items-center gap-3 text-muted-foreground">
          <span>PE ponderada</span>
          <span className="ml-auto font-mono tabular-nums text-foreground">
            {formatPercentValue(d.weightedPe)}
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

/** Tick de categoría CMF en monospace (calza con cómo se listan códigos en la app). */
const CATEGORY_TICK = { ...AXIS_TICK, fontFamily: "var(--font-mono)", fontSize: 10 }

/** Label al final de la barra: monto compacto en millones ($160 M). */
function clpLabelFmt(v: string | number | boolean | null | undefined) {
  return typeof v === "number" ? formatClpCompact(v) : ""
}

/**
 * Método estándar CMF por categoría (SDD-28 §6.4): barras horizontales de la provisión estándar
 * por categoría del Cap. B-1, ordenadas de mayor a menor (dónde vive la provisión). El código de
 * categoría `(bucket_dpd|hipotecario_sistema|mora_sistema)` se decodea a una etiqueta legible.
 * Solo grafica `provisioning_cmf.summary` ya normalizado por `cmfCategoryBars`; CERO cálculo.
 * Guard por presencia: sin categorías no renderiza.
 */
export function CmfCategoryChart({ rows }: { rows: CmfCategoryBar[] }) {
  if (rows.length === 0) return null

  // Alto proporcional al número de categorías (evita barras aplastadas).
  const height = Math.max(160, rows.length * 26 + 16)
  return (
    <div className="w-full overflow-x-auto" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={rows}
          layout="vertical"
          margin={{ top: 4, right: 60, bottom: 4, left: 8 }}
          barCategoryGap="22%"
        >
          <CartesianGrid horizontal={false} vertical stroke={GRID_STROKE} />
          <XAxis
            type="number"
            tickLine={false}
            axisLine={false}
            tick={AXIS_TICK}
            tickFormatter={(v: number) => formatClpCompact(v)}
          />
          <YAxis
            type="category"
            dataKey="label"
            width={150}
            tickLine={false}
            axisLine={AXIS_LINE}
            tick={CATEGORY_TICK}
          />
          <Tooltip cursor={CURSOR_FILL} content={<CategoryTooltip />} />
          <Bar
            dataKey="provision"
            name="Provisión"
            fill={PROVISIONING_COLORS.standard}
            radius={[0, 3, 3, 0]}
            maxBarSize={20}
            isAnimationActive={false}
          >
            <LabelList
              dataKey="provision"
              position="right"
              formatter={clpLabelFmt}
              fill={AXIS_TICK.fill}
              fontSize={9}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
