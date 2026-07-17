/**
 * Capa de presentación de los presets de la demo (IBK-03).
 *
 * El fixture/backend nombra los presets con jerga de repo («Preset estándar F1 — …») y su
 * `description` es prosa larga de config. Esta capa mapea cada preset conocido de la demo a un
 * título por ÁREA, su garantía como dato ESTRUCTURADO (no derivada de un substring de la prosa) y
 * un blurb corto. Así la landing (`DemoSelector`) y el workspace (`RunTab`) muestran el MISMO copy
 * limpio, sin tocar los fixtures `preset*.json` ni el `config_hash`.
 *
 * Encuadre LatAm: solo lo específico de CMF se rotula Chile; el scorecard (F1) e IFRS 9 (F4) son
 * genéricos LatAm. La regla del máximo del B-1 es método estándar CMF vs. método interno del banco
 * (por institución) — NUNCA un máximo entre CMF e IFRS 9, que son marcos regulatorios separados.
 */

/** Ids de los presets empaquetados en la demo (deben casar con los `preset*.json`). */
const F1_ID = "f1-estandar-consumo"
const F3_ID = "f3-provisiones-consumo"
const F4_ID = "f4-ifrs9-retail"

/** Garantía de una superficie: contrato congelado (SemVer 1.x) o experimental. */
export type Garantia = "estable" | "experimental"

/** Lo que la card/selector muestra de un preset: título por área, garantía y blurb curados. */
export interface PresetDisplay {
  /** Título limpio por área (sin la jerga «Preset F# — »). */
  title: string
  /** Garantía como dato estructurado, no un substring de la descripción. */
  garantia: Garantia
  /** Descripción corta y por área para la card. */
  blurb: string
}

/** Copy curado por área para los tres presets de la demo. */
const CURATED: Record<string, PresetDisplay> = {
  [F1_ID]: {
    title: "Scorecard de comportamiento",
    garantia: "estable",
    blurb:
      "Binning WoE monotónico, selección por IV y VIF, logística sobre WoE y calibración a " +
      "scorecard, con AUC/KS y PSI. Es la única superficie bajo garantía SemVer 1.x. Genérico LatAm.",
  },
  [F3_ID]: {
    title: "CMF vs. método interno",
    garantia: "experimental",
    blurb:
      "Provisión de consumo por el método estándar de la CMF (Chile, Cap. B-1) y por el método " +
      "interno del banco (PD·LGD·Exposición), reportando por institución el mayor de los dos, " +
      "según la regla del B-1.",
  },
  [F4_ID]: {
    title: "IFRS 9 / ECL retail",
    garantia: "experimental",
    blurb:
      "Pérdida esperada IFRS 9 de tres etapas sobre cartera retail LatAm: staging por mora 30/90 " +
      "días y ECL 12 meses / lifetime descontada a la tasa efectiva. Marco separado de la CMF.",
  },
}

/**
 * Limpia la jerga de repo del nombre de un preset NO curado (fallback): quita el prefijo
 * «Preset [algo] F# — » y capitaliza. El regex admite un token opcional entre «Preset» y «F#»
 * (p. ej. «estándar» en el nombre de F1), que la versión anterior no contemplaba.
 */
export function cleanPresetName(name: string): string {
  return name
    .replace(/^Preset\s+(?:\S+\s+)?F\d+\s*[—–-]\s*/i, "")
    .replace(/^./, (c) => c.toUpperCase())
}

/**
 * Presentación de un preset para la card/selector. Los presets conocidos de la demo usan el copy
 * curado por área; cualquier otro (backend real, presets futuros) degrada limpio: título saneado
 * por `cleanPresetName`, garantía por la palabra «experimental» de su descripción, y su descripción
 * tal cual como blurb.
 */
export function presetDisplay(preset: {
  id: string
  name: string
  description: string
}): PresetDisplay {
  const curated = CURATED[preset.id]
  if (curated) return curated
  return {
    title: cleanPresetName(preset.name),
    garantia: preset.description.toLowerCase().includes("experimental")
      ? "experimental"
      : "estable",
    blurb: preset.description,
  }
}
