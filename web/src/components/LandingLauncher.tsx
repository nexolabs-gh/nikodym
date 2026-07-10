import {
  ArrowRight,
  Boxes,
  Gauge,
  Grid3x3,
  LineChart,
  TrendingUp,
  Waves,
  type LucideIcon,
} from "lucide-react"

import { NikodymMark } from "@/components/NikodymMark"
import { ThemeToggle } from "@/components/ThemeToggle"
import { cn } from "@/lib/utils"

/**
 * Landing / launcher de nivel-0 (SDD-23 · ampliación de alcance 2026-07-07): la puerta
 * "¿qué modelo vas a construir?" ANTES del workspace. Galería de dominios del motor:
 * Scorecard (F1) está disponible en la UI; el resto ya vive en el motor (código) y su
 * visor llega en releases siguientes. CERO lógica de dominio: solo navegación.
 */

type DomainStatus = "active" | "code"

interface DomainDef {
  key: string
  label: string
  tagline: string
  icon: LucideIcon
  status: DomainStatus
}

/** Los dominios del motor. Solo `scorecard` está cableado a la UI (status "active"). */
const DOMAINS: readonly DomainDef[] = [
  {
    key: "scorecard",
    label: "Scorecard",
    tagline: "Binning → selección → modelo → scorecard → calibración → provisiones.",
    icon: Gauge,
    status: "active",
  },
  {
    key: "forward",
    label: "Forward-looking",
    tagline: "Proyección PD/LGD multi-escenario y ECL bajo IFRS 9.",
    icon: TrendingUp,
    status: "code",
  },
  {
    key: "markov",
    label: "Matrices de transición",
    tagline: "Cadenas de Markov, matrices CMF y term-structures de migración.",
    icon: Grid3x3,
    status: "code",
  },
  {
    key: "stress",
    label: "Stress testing",
    tagline: "Escenarios adversos, reverse-stress y sensibilidad del portafolio.",
    icon: Waves,
    status: "code",
  },
  {
    key: "survival",
    label: "Survival",
    tagline: "Modelos de tiempo-a-evento y curvas de hazard por cohorte.",
    icon: LineChart,
    status: "code",
  },
  {
    key: "challenger",
    label: "Challenger ML",
    tagline: "Modelos challenger (XGBoost), tuning y explicabilidad SHAP.",
    icon: Boxes,
    status: "code",
  },
]

/** Card de dominio disponible: botón premium (hover-lift, borde acento, flecha). */
function ActiveCard({ domain, onEnter }: { domain: DomainDef; onEnter: () => void }) {
  const Icon = domain.icon
  return (
    <button
      type="button"
      onClick={onEnter}
      aria-label={`Construir un ${domain.label}`}
      className={cn(
        "group relative flex flex-col gap-4 rounded-xl border border-border bg-card p-6 text-left shadow-card transition-all",
        "hover:-translate-y-0.5 hover:border-brand-accent-dark/60 hover:bg-[color-mix(in_oklch,var(--card),var(--primary)_8%)]",
      )}
    >
      <div className="flex items-start justify-between">
        <span className="flex size-11 items-center justify-center rounded-lg bg-primary/12 text-primary ring-1 ring-primary/25">
          <Icon className="size-5" aria-hidden="true" />
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-eyebrow/10 px-2.5 py-1 font-mono text-[0.62rem] font-medium uppercase tracking-[0.14em] text-eyebrow ring-1 ring-eyebrow/25">
          <span className="size-1.5 rounded-full bg-eyebrow" aria-hidden="true" />
          Disponible
        </span>
      </div>

      <div className="flex-1">
        <h2 className="font-display text-xl font-bold text-foreground">{domain.label}</h2>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
          {domain.tagline}
        </p>
      </div>

      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-accent-dark transition-transform group-hover:translate-x-0.5">
        Construir
        <ArrowRight className="size-4" aria-hidden="true" />
      </span>
    </button>
  )
}

/** Card de dominio que aún vive solo en el motor: sobria, deshabilitada, sin hover-lift. */
function CodeCard({ domain }: { domain: DomainDef }) {
  const Icon = domain.icon
  return (
    <div
      aria-disabled="true"
      className="relative flex flex-col gap-4 rounded-xl border border-border bg-muted/40 p-6"
    >
      <div className="flex items-start justify-between">
        <span className="flex size-11 items-center justify-center rounded-lg bg-foreground/[0.05] text-muted-foreground">
          <Icon className="size-5" aria-hidden="true" />
        </span>
        <span className="rounded-full bg-foreground/[0.05] px-2.5 py-1 font-mono text-[0.62rem] font-medium uppercase tracking-[0.14em] text-muted-foreground">
          En código
        </span>
      </div>

      <div className="flex-1">
        <h2 className="font-display text-xl font-bold text-muted-foreground">
          {domain.label}
        </h2>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
          {domain.tagline}
        </p>
      </div>

      <span className="font-mono text-[0.7rem] uppercase tracking-[0.12em] text-muted-foreground/70">
        Visor en camino
      </span>
    </div>
  )
}

/** Pantalla de nivel-0: `onEnter` entra al workspace (flujo F1 del scorecard). */
export function LandingLauncher({ onEnter }: { onEnter: () => void }) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-background text-foreground">
      {/* Glow navy decorativo, muy tenue (sombra de la casa, nunca glow de acento fuerte) */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[60vh] bg-[radial-gradient(60%_50%_at_50%_0%,rgba(46,111,242,0.10),transparent_70%)]"
      />

      <div className="relative mx-auto flex min-h-screen max-w-6xl flex-col px-6 py-8 lg:px-10">
        {/* Barra de marca */}
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <NikodymMark className="size-8" />
            <span className="font-display text-xl font-bold tracking-tight text-foreground">
              Nikodym
            </span>
            <span className="mt-1 font-mono text-[0.7rem] uppercase tracking-[0.18em] text-muted-foreground">
              RiskLib
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span className="hidden font-mono text-xs text-muted-foreground sm:inline">
              pip install nikodym
            </span>
            <ThemeToggle />
          </div>
        </header>

        {/* Hero + galería */}
        <main className="flex flex-1 flex-col justify-center py-14">
          <p className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-eyebrow">
            Motor de riesgo de crédito · V1
          </p>
          <h1 className="max-w-3xl font-display text-4xl font-bold tracking-tight text-foreground sm:text-5xl">
            ¿Qué modelo vas a construir?
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-relaxed text-muted-foreground">
            Del dato crudo al scorecard regulatorio — binning, selección, modelo,
            calibración y provisiones. Reproducible y auditable, del mismo código que
            corre en producción.
          </p>

          <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {DOMAINS.map((domain) =>
              domain.status === "active" ? (
                <ActiveCard key={domain.key} domain={domain} onEnter={onEnter} />
              ) : (
                <CodeCard key={domain.key} domain={domain} />
              ),
            )}
          </div>
        </main>

        {/* Footer sutil */}
        <footer className="flex items-center justify-between border-t border-border pt-6">
          <span className="font-mono text-[0.7rem] uppercase tracking-[0.14em] text-muted-foreground">
            Nikodym RiskLib · Apache-2.0
          </span>
          <span className="font-mono text-[0.7rem] text-muted-foreground">
            El motor ya calcula los 6 dominios · la UI llega por release
          </span>
        </footer>
      </div>
    </div>
  )
}
