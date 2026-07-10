import type { ReactNode } from "react"

import { EMPTY } from "@/lib/results-format"

/** Ítem del payload que inyecta Recharts (subconjunto que consumimos). */
interface TooltipItem {
  name?: string | number
  value?: number | string | ReadonlyArray<number | string>
  color?: string
  dataKey?: string | number
}

interface ChartTooltipProps {
  /** Recharts lo inyecta al pasar `<ChartTooltip />` a `Tooltip.content`. */
  active?: boolean
  label?: ReactNode
  payload?: ReadonlyArray<TooltipItem>
  /** Formatea cada valor numérico (default: 4 decimales, como las tablas). */
  formatValue?: (v: number) => string
  /** Oculta el título (útil cuando el label duplica la categoría del eje). */
  hideLabel?: boolean
}

function defaultFormat(v: number): string {
  return v.toFixed(4)
}

/**
 * Tooltip de los visores estilizado con los tokens/Card de la app (panel navy
 * elevado con ring), NO el tooltip blanco default de Recharts. Presentación pura:
 * solo formatea los valores que Recharts ya calculó a partir de `results`.
 */
export function ChartTooltip({
  active,
  label,
  payload,
  formatValue = defaultFormat,
  hideLabel = false,
}: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null

  const showLabel =
    !hideLabel && label !== undefined && label !== null && label !== ""

  return (
    <div className="rounded-lg bg-secondary px-3 py-2 text-xs shadow-card ring-1 ring-foreground/10">
      {showLabel ? (
        <p className="mb-1.5 font-medium text-foreground">{label}</p>
      ) : null}
      <ul className="space-y-1">
        {payload.map((item, i) => {
          const value =
            typeof item.value === "number" ? formatValue(item.value) : EMPTY
          return (
            <li
              key={`${String(item.dataKey ?? item.name ?? i)}`}
              className="flex items-center gap-2"
            >
              <span
                className="size-2 shrink-0 rounded-[2px]"
                style={{ backgroundColor: item.color ?? "var(--brand-gray)" }}
                aria-hidden="true"
              />
              <span className="text-muted-foreground">{item.name}</span>
              <span className="ml-auto pl-3 font-mono tabular-nums text-foreground">
                {value}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
