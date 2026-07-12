import { cn } from "@/lib/utils"

/** Un paso del flujo; `optional` marca los que NO son un peaje (hoy: Configuración). */
export interface FlowStep {
  label: string
  optional?: boolean
}

interface FlowStepperProps {
  steps: FlowStep[]
  /** Índice (0-based) del paso actual. */
  current: number
}

/**
 * Stepper horizontal PRESENTACIONAL del workspace: pinta ①─②─③ con el paso actual resaltado en
 * acento de marca, para que se vea dónde se está y cuánto falta. Sin lógica de negocio ni estado
 * propio: el paso activo lo deriva `App` de la sección abierta en el sidebar (que sigue siendo el
 * navegador real; el stepper no navega).
 *
 * Los pasos `optional` se rotulan como tales: desde UX1 el config estándar se siembra y valida
 * solo al entrar, así que Configuración es un ajuste opcional, no un requisito para ejecutar.
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
                {step.optional ? (
                  <span className="hidden font-mono text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground sm:inline">
                    opcional
                  </span>
                ) : null}
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
