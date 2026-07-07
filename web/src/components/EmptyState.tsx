import type { LucideIcon } from "lucide-react"

interface EmptyStateProps {
  icon: LucideIcon
  title: string
  description: string
  /** Etiqueta de estado (p.ej. el bloque que lo entregará). */
  tag?: string
}

/** Estado vacío sobrio, reutilizable por cada pestaña del shell (placeholder). */
export function EmptyState({
  icon: Icon,
  title,
  description,
  tag = "Próximamente",
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-4 px-6 py-16 text-center">
      <div className="flex size-14 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-brand-cyan">
        <Icon className="size-6" aria-hidden="true" />
      </div>
      <div className="space-y-1.5">
        <h3 className="font-display text-lg font-medium text-brand-offwhite">
          {title}
        </h3>
        <p className="mx-auto max-w-md text-sm leading-relaxed text-muted-foreground">
          {description}
        </p>
      </div>
      <span className="rounded-full border border-brand-accent-dark/30 bg-brand-accent/10 px-3 py-1 font-mono text-[0.68rem] uppercase tracking-[0.14em] text-brand-accent-dark">
        {tag}
      </span>
    </div>
  )
}
