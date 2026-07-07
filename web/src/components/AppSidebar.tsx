import type { LucideIcon } from "lucide-react"

import { AppHeader } from "@/components/AppHeader"
import { cn } from "@/lib/utils"

interface AppSidebarProps {
  items: readonly { value: string; label: string; icon: LucideIcon }[]
  active: string
  onSelect: (value: string) => void
}

/**
 * Sidebar navy de marca: brand header + nav vertical + slot de estado de corrida.
 *
 * Sidebar propio liviano (D-UI-B234a-rev-1): NO usa el componente `sidebar` de
 * shadcn, que arrastra SidebarProvider/context/cookies/sheet móvil y varias deps;
 * para 5 items un contenedor propio con los tokens de marca es más liviano y da
 * control total. Responsive: rail de iconos (w-16) en < lg, expandido (w-60) en lg+.
 */
export function AppSidebar({ items, active, onSelect }: AppSidebarProps) {
  return (
    <aside className="sticky top-0 flex h-screen w-16 shrink-0 flex-col border-r border-white/10 bg-sidebar lg:w-60">
      <AppHeader />

      <nav
        aria-label="Secciones"
        className="flex flex-1 flex-col gap-1 overflow-y-auto px-2 py-2 lg:px-3"
      >
        {items.map((item) => {
          const Icon = item.icon
          const isActive = item.value === active
          return (
            <button
              key={item.value}
              type="button"
              onClick={() => onSelect(item.value)}
              aria-current={isActive ? "page" : undefined}
              title={item.label}
              className={cn(
                "relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                "justify-center lg:justify-start",
                isActive
                  ? "bg-primary text-white"
                  : "text-brand-placeholder hover:bg-white/5 hover:text-brand-offwhite",
              )}
            >
              {/* Indicador de sección activa: barra cyan al borde izquierdo */}
              <span
                className={cn(
                  "absolute top-1/2 left-0 h-5 w-0.5 -translate-y-1/2 rounded-full bg-brand-cyan transition-opacity",
                  isActive ? "opacity-100" : "opacity-0",
                )}
                aria-hidden="true"
              />
              <Icon className="size-4 shrink-0" aria-hidden="true" />
              <span className="hidden lg:inline">{item.label}</span>
            </button>
          )
        })}
      </nav>

      {/* Slot de meta-info de corrida (placeholders; B23.5 lo cablea). Oculto en rail. */}
      <div className="hidden border-t border-white/10 px-4 py-4 lg:block">
        <p className="mb-2 font-mono text-[0.62rem] uppercase tracking-[0.14em] text-brand-gray">
          Estado de corrida
        </p>
        <dl className="space-y-1 font-mono text-xs text-brand-placeholder">
          <div className="flex justify-between gap-2">
            <dt className="text-brand-gray">Corrida</dt>
            <dd>—</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-brand-gray">config_hash</dt>
            <dd>—</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-brand-gray">Dataset</dt>
            <dd>—</dd>
          </div>
        </dl>
      </div>
    </aside>
  )
}
