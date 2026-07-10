import { useCallback, useState } from "react"

export type Theme = "light" | "dark"

const STORAGE_KEY = "nikodym-theme"

/** Tema actual leído del DOM (la clase `.dark` la fija el script inline de index.html). */
function currentTheme(): Theme {
  if (typeof document === "undefined") return "dark"
  return document.documentElement.classList.contains("dark") ? "dark" : "light"
}

/**
 * Estado del tema claro/oscuro. La fuente de verdad es la clase `.dark` en <html>
 * (aplicada sin flash por el script de index.html); el toggle la conmuta y persiste la
 * elección en localStorage. Default de la casa = oscuro (navy). Landing y workspace son
 * vistas excluyentes, así que no hay dos toggles montados a la vez que desincronizar.
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(currentTheme)

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark"
      document.documentElement.classList.toggle("dark", next === "dark")
      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {
        /* localStorage no disponible (modo privado): el tema vive solo en memoria. */
      }
      return next
    })
  }, [])

  return { theme, toggle }
}
