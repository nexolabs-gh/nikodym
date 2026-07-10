import { cn } from "@/lib/utils"

interface FlowStepperProps {
  steps: { label: string }[]
  /** Índice (0-based) del paso actual. */
  current: number
}

/**
 * Stepper horizontal PRESENTACIONAL para el modo demo (B23.6). Sin lógica de
 * negocio: solo pinta ①─②─③ con el paso actual resaltado en acento de marca.
 *
 * NO se monta por default (D-UI-B234a-rev-3): el modo local del analista navega
 * libre por el sidebar. B23.6 lo renderizará sobre el área de contenido cuando
 * `mode === "demo"`. Sin test unit: aún no hay runner (vitest) — pendiente B23.5.
 */
export function FlowStepper({ steps, current }: FlowStepperProps) {
  return (
    <nav aria-label="Progreso del flujo" className="mb-8">
      <ol className="flex items-center">
        {steps.map((step, index) => {
          const isActive = index === current
          const isComplete = index < current
          return (
            <li key={step.label} className="flex items-center">
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold transition-colors",
                    isActive
                      ? "border-brand-accent bg-brand-accent text-primary-foreground"
                      : isComplete
                        ? "border-brand-accent-dark/60 bg-brand-accent/20 text-brand-accent-dark"
                        : "border-border text-muted-foreground",
                  )}
                  aria-current={isActive ? "step" : undefined}
                >
                  {index + 1}
                </span>
                <span
                  className={cn(
                    "hidden text-sm sm:inline",
                    isActive
                      ? "font-medium text-foreground"
                      : "text-muted-foreground",
                  )}
                >
                  {step.label}
                </span>
              </div>
              {index < steps.length - 1 && (
                <span
                  className="mx-3 h-px w-6 bg-foreground/15 sm:w-10"
                  aria-hidden="true"
                />
              )}
            </li>
          )
        })}
      </ol>
      <p className="mt-3 font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
        Paso {current + 1} de {steps.length}
      </p>
    </nav>
  )
}
