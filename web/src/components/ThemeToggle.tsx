import { Moon, Sun } from "lucide-react"

import { useTheme } from "@/lib/use-theme"
import { cn } from "@/lib/utils"

/** Botón sol/luna que conmuta el tema claro/oscuro (persiste la elección). */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme()
  const isDark = theme === "dark"
  const label = isDark ? "Cambiar a modo claro" : "Cambiar a modo oscuro"
  return (
    <button
      type="button"
      onClick={toggle}
      title={label}
      aria-label={label}
      className={cn(
        "inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
        className,
      )}
    >
      {isDark ? (
        <Sun className="size-4" aria-hidden="true" />
      ) : (
        <Moon className="size-4" aria-hidden="true" />
      )}
    </button>
  )
}
