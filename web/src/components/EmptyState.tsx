import { ArrowRight, type LucideIcon } from "lucide-react"

import { Button } from "@/components/ui/button"

/** CTA opcional del estado vacío: lleva al paso del flujo que destraba la pantalla. */
export interface EmptyStateAction {
  label: string
  onClick: () => void
  /** Icono del paso destino (p.ej. `Play` para Ejecutar); la flecha la pone el botón. */
  icon?: LucideIcon
}

interface EmptyStateProps {
  icon: LucideIcon
  title: string
  description: string
  /** Etiqueta de estado (p.ej. el bloque que lo entregará). */
  tag?: string
  /** Botón que NAVEGA al paso que falta; sin él, el estado vacío es solo texto. */
  action?: EmptyStateAction
}

/** Estado vacío sobrio, reutilizable por cada pestaña del shell, con CTA opcional al paso siguiente. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  tag = "Próximamente",
  action,
}: EmptyStateProps) {
  const ActionIcon = action?.icon
  return (
    <div className="flex flex-col items-center gap-4 px-6 py-16 text-center">
      <div className="flex size-14 items-center justify-center rounded-2xl border border-border bg-foreground/5 text-eyebrow">
        <Icon className="size-6" aria-hidden="true" />
      </div>
      <div className="space-y-1.5">
        <h3 className="font-display text-lg font-medium text-foreground">
          {title}
        </h3>
        <p className="mx-auto max-w-md text-sm leading-relaxed text-muted-foreground">
          {description}
        </p>
      </div>
      <span className="rounded-full border border-brand-accent-dark/30 bg-brand-accent/10 px-3 py-1 font-mono text-[0.68rem] uppercase tracking-[0.14em] text-brand-accent-dark">
        {tag}
      </span>
      {action ? (
        <Button variant="outline" size="sm" onClick={action.onClick}>
          {ActionIcon ? <ActionIcon aria-hidden="true" /> : null}
          {action.label}
          <ArrowRight aria-hidden="true" />
        </Button>
      ) : null}
    </div>
  )
}
