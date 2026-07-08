import type { LucideIcon } from "lucide-react"

import { AppHeader } from "@/components/AppHeader"
import { cn } from "@/lib/utils"
import { useAppState } from "@/state/appStore"

/** Una hoja de navegación (item seleccionable del sidebar). */
export interface NavChild {
  value: string
  label: string
  icon: LucideIcon
}

/** Un item de nivel superior: hoja suelta o grupo con `children` anidados. */
export interface NavItem extends NavChild {
  children?: readonly NavChild[]
}

interface AppSidebarProps {
  items: readonly NavItem[]
  active: string
  onSelect: (value: string) => void
}

/** Botón de navegación (hoja): icono + label + barra cyan de "activo". `indent` para sub-items. */
function NavButton({
  item,
  active,
  onSelect,
  indent = false,
}: {
  item: NavChild
  active: string
  onSelect: (value: string) => void
  indent?: boolean
}) {
  const Icon = item.icon
  const isActive = item.value === active
  return (
    <button
      type="button"
      onClick={() => onSelect(item.value)}
      aria-current={isActive ? "page" : undefined}
      title={item.label}
      className={cn(
        "relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
        "justify-center lg:justify-start",
        indent && "lg:pl-6",
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
}

/**
 * Sidebar navy de marca: brand header + nav vertical + slot de estado de corrida.
 *
 * Sidebar propio liviano (D-UI-B234a-rev-1): NO usa el componente `sidebar` de
 * shadcn, que arrastra SidebarProvider/context/cookies/sheet móvil y varias deps;
 * para pocos items un contenedor propio con los tokens de marca es más liviano y da
 * control total. Responsive: rail de iconos (w-16) en < lg, expandido (w-60) en lg+.
 *
 * B30: un item de nivel superior puede tener `children` (grupo "Configuración" → sus 7
 * sub-secciones), que se pintan anidados con un encabezado de grupo (solo en lg) y un
 * separador; en el rail los hijos quedan como su propia pila de iconos.
 */
export function AppSidebar({ items, active, onSelect }: AppSidebarProps) {
  // Estado de corrida REAL desde el store (SDD-23 §7.4): run_id/config_hash/dataset.
  const { lastRun, validation, datasetId } = useAppState()
  const configHash = validation.kind === "valid" ? validation.hash : null

  return (
    <aside className="sticky top-0 flex h-screen w-16 shrink-0 flex-col border-r border-white/10 bg-sidebar lg:w-60">
      <AppHeader />

      <nav
        aria-label="Secciones"
        className="flex flex-1 flex-col gap-1 overflow-y-auto px-2 py-2 lg:px-3"
      >
        {items.map((item) =>
          item.children && item.children.length > 0 ? (
            <div key={item.value} className="flex flex-col gap-1">
              <p className="hidden px-3 pt-1 pb-0.5 font-mono text-[0.62rem] uppercase tracking-[0.14em] text-brand-gray lg:block">
                {item.label}
              </p>
              {item.children.map((child) => (
                <NavButton
                  key={child.value}
                  item={child}
                  active={active}
                  onSelect={onSelect}
                  indent
                />
              ))}
              <div
                className="mx-3 my-1 border-b border-white/5"
                aria-hidden="true"
              />
            </div>
          ) : (
            <NavButton
              key={item.value}
              item={item}
              active={active}
              onSelect={onSelect}
            />
          ),
        )}
      </nav>

      {/* Slot de meta-info de corrida, cableado al store. Sin corrida: guiones. Oculto en rail. */}
      <div className="hidden border-t border-white/10 px-4 py-4 lg:block">
        <p className="mb-2 font-mono text-[0.62rem] uppercase tracking-[0.14em] text-brand-gray">
          Estado de corrida
        </p>
        <dl className="space-y-1 font-mono text-xs text-brand-placeholder">
          <div className="flex justify-between gap-2">
            <dt className="shrink-0 text-brand-gray">Corrida</dt>
            <dd
              className={cn(
                "min-w-0 truncate text-right",
                lastRun?.status === "failed" && "text-amber-200/80",
                lastRun?.status === "done" && "text-brand-cyan",
              )}
              title={lastRun?.runId}
            >
              {lastRun ? lastRun.runId : "—"}
            </dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="shrink-0 text-brand-gray">config_hash</dt>
            <dd
              className="min-w-0 truncate text-right"
              title={configHash ?? undefined}
            >
              {configHash ?? "—"}
            </dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="shrink-0 text-brand-gray">Dataset</dt>
            <dd
              className="min-w-0 truncate text-right"
              title={datasetId ?? undefined}
            >
              {datasetId ?? "—"}
            </dd>
          </div>
        </dl>
      </div>
    </aside>
  )
}
