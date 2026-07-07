import {
  createContext,
  useContext,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react"

import type { RunStatus } from "@/lib/api"
import type { ValidationState } from "@/lib/validation"

/** Identidad de la última corrida disparada (SDD-23 §7.4): id + estado terminal. */
export interface LastRun {
  runId: string
  status: RunStatus
}

/**
 * Estado compartido mínimo entre pestañas (Config → Ejecutar → Resultados), como React
 * Context liviano y SIN dependencia nueva (SDD-23 §3.5). El front NO calcula dominio: solo
 * transporta el config editado, su validación (producida por el backend), el dataset elegido
 * y la identidad/artefactos de la última corrida. Los setters son los de `useState` (estables),
 * así que soportan tanto un valor nuevo como un updater `(prev) => next`.
 */
export interface AppState {
  config: Record<string, unknown>
  setConfig: Dispatch<SetStateAction<Record<string, unknown>>>
  datasetId: string | null
  setDatasetId: Dispatch<SetStateAction<string | null>>
  validation: ValidationState
  setValidation: Dispatch<SetStateAction<ValidationState>>
  lastRun: LastRun | null
  setLastRun: Dispatch<SetStateAction<LastRun | null>>
  results: Record<string, unknown> | null
  setResults: Dispatch<SetStateAction<Record<string, unknown> | null>>
}

const AppStateContext = createContext<AppState | null>(null)

/** Provider del estado compartido. Envuelve <App/> en main.tsx. */
export function AppStateProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [validation, setValidation] = useState<ValidationState>({ kind: "idle" })
  const [lastRun, setLastRun] = useState<LastRun | null>(null)
  const [results, setResults] = useState<Record<string, unknown> | null>(null)

  // Los setters de useState son estables → el value solo cambia con el estado real.
  const value = useMemo<AppState>(
    () => ({
      config,
      setConfig,
      datasetId,
      setDatasetId,
      validation,
      setValidation,
      lastRun,
      setLastRun,
      results,
      setResults,
    }),
    [config, datasetId, validation, lastRun, results],
  )

  return <AppStateContext value={value}>{children}</AppStateContext>
}

/** Acceso al estado compartido; lanza un error claro si se usa fuera del provider. */
export function useAppState(): AppState {
  const ctx = useContext(AppStateContext)
  if (ctx === null) {
    throw new Error(
      "useAppState() debe usarse dentro de <AppStateProvider> (envuelve <App/> en main.tsx).",
    )
  }
  return ctx
}
