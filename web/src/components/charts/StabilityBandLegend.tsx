import type { StabilityBand } from "@/lib/results-types"

import { bandColor, bandLabel } from "./chart-theme"

/**
 * Leyenda accesible de las bandas de estabilidad: chip de color + etiqueta textual (el
 * significado NUNCA queda solo en el color). Presentación pura; las bandas a mostrar las
 * decide el llamador (`bandsPresent`), de modo que la leyenda refleja la escala semántica
 * —estable/revisar/redesarrollar— aunque en la corrida todo caiga en `stable`.
 */
export function StabilityBandLegend({ bands }: { bands: StabilityBand[] }) {
  if (bands.length === 0) return null
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[0.7rem] text-muted-foreground">
      {bands.map((band) => (
        <li key={band} className="flex items-center gap-1.5">
          <span
            className="size-2 rounded-full"
            style={{ backgroundColor: bandColor(band) }}
            aria-hidden="true"
          />
          {bandLabel(band)}
        </li>
      ))}
    </ul>
  )
}
