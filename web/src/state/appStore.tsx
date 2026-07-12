import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react"

import { validateConfig, type ResultsResponse, type RunStatus } from "@/lib/api"
import {
  bootstrapOnce,
  seedDatasetId,
  type SeedState,
} from "@/lib/bootstrap"
import type { SelectedDataset } from "@/lib/datasets"
import type { LoadedSchema } from "@/lib/schema"
import { buildErrorLookup, type ValidationState } from "@/lib/validation"

/** Identidad de la última corrida disparada (SDD-23 §7.4): id + estado terminal. */
export interface LastRun {
  runId: string
  status: RunStatus
}

/** Debounce de la validación en vivo: no congela la edición (SDD-23 §3.3, restricción). */
const VALIDATE_DEBOUNCE_MS = 350

/**
 * Estado compartido mínimo entre pestañas (Datos → Config → Ejecutar → Resultados), como React
 * Context liviano y SIN dependencia nueva (SDD-23 §3.5). El front NO calcula dominio: solo
 * transporta el config editado, su validación (producida por el backend), el dataset elegido
 * y la identidad/artefactos de la última corrida. Los setters son los de `useState` (estables),
 * así que soportan tanto un valor nuevo como un updater `(prev) => next`.
 *
 * El provider además SIEMBRA el config al arrancar y lo valida en vivo (antes vivía en
 * `ConfigTab`): entrar al workspace basta para poder ejecutar, sin tocar Configuración.
 */
export interface AppState {
  /** Schema del formulario (SDD-23 §3.2); `null` mientras arranca la sesión. */
  schema: LoadedSchema | null
  config: Record<string, unknown>
  setConfig: Dispatch<SetStateAction<Record<string, unknown>>>
  /** Qué config está sembrado (preset / defaults / fallback); `null` mientras arranca. */
  seed: SeedState | null
  setSeed: Dispatch<SetStateAction<SeedState | null>>
  datasetId: string | null
  setDatasetId: Dispatch<SetStateAction<string | null>>
  /** Dataset elegido, normalizado para el preview (catálogo o subida); persiste entre pestañas. */
  selectedDataset: SelectedDataset | null
  setSelectedDataset: Dispatch<SetStateAction<SelectedDataset | null>>
  validation: ValidationState
  setValidation: Dispatch<SetStateAction<ValidationState>>
  lastRun: LastRun | null
  setLastRun: Dispatch<SetStateAction<LastRun | null>>
  results: ResultsResponse | null
  setResults: Dispatch<SetStateAction<ResultsResponse | null>>
  /** Tarjeta de bienvenida (get-started) cerrada por el usuario en esta sesión. */
  welcomeDismissed: boolean
  setWelcomeDismissed: Dispatch<SetStateAction<boolean>>
}

const AppStateContext = createContext<AppState | null>(null)

/** Provider del estado compartido. Envuelve <App/> en main.tsx. */
export function AppStateProvider({ children }: { children: ReactNode }) {
  const [schema, setSchema] = useState<LoadedSchema | null>(null)
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [seed, setSeed] = useState<SeedState | null>(null)
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [selectedDataset, setSelectedDataset] =
    useState<SelectedDataset | null>(null)
  const [validation, setValidation] = useState<ValidationState>({ kind: "idle" })
  const [lastRun, setLastRun] = useState<LastRun | null>(null)
  const [results, setResults] = useState<ResultsResponse | null>(null)
  const [welcomeDismissed, setWelcomeDismissed] = useState(false)
  const requestSeq = useRef(0)

  // Arranque de la sesión: carga el schema y siembra el PRESET ESTÁNDAR (config completo +
  // dataset recomendado) SIN depender de que se abra Configuración → entrar al workspace basta
  // para poder ejecutar. `bootstrapOnce` memoiza la siembra: ocurre una sola vez por sesión, así
  // que no puede pisar lo que el usuario ya editó (y `seedDatasetId` respeta un dataset ya
  // elegido si la elección le ganó la carrera al preset). Si el backend está caído, el arranque
  // cae a los defaults del schema (`fallback`) sin crashear.
  useEffect(() => {
    let alive = true
    void bootstrapOnce().then((outcome) => {
      if (!alive) return
      setSchema(outcome.schema)
      setConfig(structuredClone(outcome.config))
      setDatasetId((previous) => seedDatasetId(previous, outcome))
      setSeed(outcome.seed)
    })
    return () => {
      alive = false
    }
  }, [])

  // Validación en vivo (SDD-23 §3.3/§7): en cada cambio del config re-valida en el backend con
  // debounce. El timer previo se cancela en el cleanup; el contador `requestSeq` descarta
  // respuestas obsoletas (última petición gana). Corre desde el arranque —no desde el montaje de
  // Configuración—, así que el `config_hash` en vivo existe aunque el usuario nunca configure.
  useEffect(() => {
    if (schema === null) return
    const seq = ++requestSeq.current
    setValidation({ kind: "checking" })
    const timer = setTimeout(() => {
      void validateConfig(config)
        .then((res) => {
          if (seq !== requestSeq.current) return // respuesta obsoleta
          if (res.valid && res.config_hash) {
            setValidation({ kind: "valid", hash: res.config_hash })
          } else {
            setValidation({
              kind: "invalid",
              count: res.errors.length,
              lookup: buildErrorLookup(res.errors),
            })
          }
        })
        .catch(() => {
          if (seq !== requestSeq.current) return
          setValidation({ kind: "unreachable" }) // degrada suave; NO inventa hash
        })
    }, VALIDATE_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [config, schema])

  // Los setters de useState son estables → el value solo cambia con el estado real.
  const value = useMemo<AppState>(
    () => ({
      schema,
      config,
      setConfig,
      seed,
      setSeed,
      datasetId,
      setDatasetId,
      selectedDataset,
      setSelectedDataset,
      validation,
      setValidation,
      lastRun,
      setLastRun,
      results,
      setResults,
      welcomeDismissed,
      setWelcomeDismissed,
    }),
    [
      schema,
      config,
      seed,
      datasetId,
      selectedDataset,
      validation,
      lastRun,
      results,
      welcomeDismissed,
    ],
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
