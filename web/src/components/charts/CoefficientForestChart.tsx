import {
  ErrorBar,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { Coefficient } from "@/lib/results-types"

import { AXIS_LINE, AXIS_TICK, BRAND, coefColor, niceBound } from "./chart-theme"

/** Punto del forest plot: β, su intervalo como error asimétrico y el flag de signo. */
interface ForestDatum {
  feature: string
  beta: number
  /** [β − conf_low, conf_high − β] → error bar asimétrico que Recharts dibuja como IC. */
  ciError: [number, number]
  signOk: boolean | null
}

/**
 * Deriva los puntos del forest plot desde `model.coefficients`. Excluye el intercepto
 * (no es un efecto de variable y su magnitud aplastaría la escala) y ordena por β. NO
 * recalcula: solo transporta β/IC/`sign_ok` ya materializados.
 */
function buildForest(coefs: Coefficient[]): ForestDatum[] {
  return coefs
    .filter((c) => c.feature !== "intercept" && c.expected_sign !== "none")
    .map((c) => ({
      feature: c.feature,
      beta: c.beta,
      ciError: [
        Math.max(0, c.beta - c.conf_low),
        Math.max(0, c.conf_high - c.beta),
      ] as [number, number],
      signOk: c.sign_ok,
    }))
    .sort((a, b) => b.beta - a.beta)
}

/** Props que Recharts inyecta al `shape` del punto (Scatter posiciona `cx/cy` fiable). */
interface ForestDotShapeProps {
  cx?: number
  cy?: number
  payload?: ForestDatum
}

/**
 * Punto del forest plot en (β, variable), coloreado según `sign_ok`. Va sobre un
 * `Scatter` (no `Bar`): el Scatter posiciona `cx/cy` por dato de forma fiable, mientras
 * que el rectángulo de un Bar horizontal con valores negativos se computa mal en v3.
 * El error bar (whiskers del IC) y la línea de 0 se dibujan aparte.
 */
function ForestDot({ cx, cy, payload }: ForestDotShapeProps) {
  if (cx === undefined || cy === undefined) return null
  const color = coefColor(payload?.signOk)
  return <circle cx={cx} cy={cy} r={4.5} fill={color} />
}

/** Ítem del payload del tooltip (Recharts inyecta el datum en `.payload`). */
interface ForestTooltipProps {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: ForestDatum }>
}

/** Tooltip dedicado: muestra β y el intervalo de confianza [conf_low, conf_high]. */
function ForestTooltip({ active, payload }: ForestTooltipProps) {
  const d = active && payload && payload.length > 0 ? payload[0]?.payload : null
  if (!d) return null
  const low = d.beta - d.ciError[0]
  const high = d.beta + d.ciError[1]
  return (
    <div className="rounded-lg bg-secondary px-3 py-2 text-xs shadow-card ring-1 ring-foreground/10">
      <p className="mb-1 font-mono font-medium text-foreground">
        {d.feature}
      </p>
      <p className="text-muted-foreground">
        β{" "}
        <span className="ml-1 font-mono tabular-nums text-foreground">
          {d.beta.toFixed(4)}
        </span>
      </p>
      <p className="text-muted-foreground">
        IC{" "}
        <span className="ml-1 font-mono tabular-nums text-foreground">
          [{low.toFixed(4)}, {high.toFixed(4)}]
        </span>
      </p>
      <p className="mt-1 text-[0.7rem]">
        {d.signOk === false ? (
          <span className="text-amber-200/90">signo inesperado</span>
        ) : (
          <span className="text-eyebrow">signo esperado</span>
        )}
      </p>
    </div>
  )
}

/**
 * Forest plot de coeficientes: un punto por variable en β con su intervalo de confianza
 * como error bar horizontal, línea vertical en 0 y color por `sign_ok`. Solo grafica
 * `model.coefficients`; guarda por presencia (si tras excluir el intercepto no queda
 * nada, no renderiza).
 */
export function CoefficientForestChart({
  coefficients,
}: {
  coefficients: Coefficient[]
}) {
  const data = buildForest(coefficients)
  if (data.length === 0) return null

  // Dominio simétrico alrededor de 0 (incluye los extremos del IC) → 0 queda centrado.
  const maxAbs = Math.max(
    ...data.map((d) =>
      Math.max(
        Math.abs(d.beta - d.ciError[0]),
        Math.abs(d.beta + d.ciError[1]),
      ),
    ),
  )
  const bound = niceBound(maxAbs)
  const height = Math.max(140, data.length * 46 + 20)

  return (
    <div className="space-y-2">
      <div className="w-full" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
            <XAxis
              type="number"
              dataKey="beta"
              domain={[-bound, bound]}
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
              tick={{ ...AXIS_TICK, fontFamily: "var(--font-mono)" }}
            />
            <ReferenceLine
              x={0}
              stroke="var(--border)"
              strokeWidth={1}
            />
            <Tooltip
              cursor={{ strokeDasharray: "3 3", stroke: "var(--border)" }}
              content={<ForestTooltip />}
            />
            <Scatter
              data={data}
              shape={<ForestDot />}
              isAnimationActive={false}
            >
              <ErrorBar
                dataKey="ciError"
                direction="x"
                width={5}
                strokeWidth={1.5}
                stroke={BRAND.placeholder}
              />
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      {/* Leyenda del color (accesibilidad: el significado no queda solo en el color). */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.7rem] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span
            className="size-2 rounded-full"
            style={{ backgroundColor: BRAND.cyan }}
            aria-hidden="true"
          />
          signo esperado
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="size-2 rounded-full"
            style={{ backgroundColor: BRAND.amber }}
            aria-hidden="true"
          />
          signo inesperado
        </span>
        <span className="text-muted-foreground">— barra de error = intervalo de confianza</span>
      </div>
    </div>
  )
}
