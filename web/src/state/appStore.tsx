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

import {
  preflightDataset,
  validateConfig,
  type ExternalArtifactRef,
  type ResultsResponse,
  type RunStatus,
} from "@/lib/api"
import {
  bootstrapOnce,
  seedDatasetId,
  type SeedState,
} from "@/lib/bootstrap"
import type { SelectedDataset } from "@/lib/datasets"
import { DEMO_MODE } from "@/lib/demo-runtime"
import {
  externalRefs as buildExternalRefs,
  requiredExternalArtifacts,
  type ExternalInput,
} from "@/lib/external-artifacts"
import type { ExternalArtifact, Job } from "@/lib/jobs"
import type { PreflightState } from "@/lib/preflight"
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
  /**
   * Trabajo elegido esta sesión (D-JOB-1): decide qué secciones existen en el sidebar. `null` =
   * ninguno, y entonces se ven todas — es el estado de quien trajo un config que no calza con
   * ningún trabajo del catálogo, sea un YAML propio o un ejemplo (D-JOB-17).
   *
   * NO entra al `config_hash` (D-JOB-9): es navegación. Dos usuarios que llegan al mismo config
   * por trabajos distintos producen la misma identidad, y un gate lo vigila.
   */
  job: Job | null
  setJob: Dispatch<SetStateAction<Job | null>>
  config: Record<string, unknown>
  setConfig: Dispatch<SetStateAction<Record<string, unknown>>>
  /** Qué config está sembrado (preset / defaults / fallback); `null` mientras arranca. */
  seed: SeedState | null
  setSeed: Dispatch<SetStateAction<SeedState | null>>
  datasetId: string | null
  setDatasetId: Dispatch<SetStateAction<string | null>>
  /**
   * Archivos que el usuario trae de fuera, por clave de artefacto (D-PUE-3/5).
   *
   * Vive en el store y no en la pestaña de Datos porque lo consumen tres sitios en pestañas
   * distintas: la validación en vivo y el preflight (que necesitan saber qué va a estar), y el
   * botón de ejecutar. Guarda las columnas del archivo porque son las opciones de los selectores
   * del mapeo: se elige de una lista real, no se teclea un nombre.
   */
  externalInputs: Record<string, ExternalInput>
  setExternalInputs: Dispatch<SetStateAction<Record<string, ExternalInput>>>
  /** Los insumos que el trabajo pide CON EL CONFIG ACTUAL, ya resueltas sus condiciones. */
  requiredExternals: ExternalArtifact[]
  /** El cuerpo que viaja al backend: una referencia por insumo pedido y ya cubierto. */
  externalRefs: ExternalArtifactRef[]
  /** Dataset elegido, normalizado para el preview (catálogo o subida); persiste entre pestañas. */
  selectedDataset: SelectedDataset | null
  setSelectedDataset: Dispatch<SetStateAction<SelectedDataset | null>>
  validation: ValidationState
  setValidation: Dispatch<SetStateAction<ValidationState>>
  /** Veredicto config↔dataset en vivo (D-PRE-1); `idle` mientras la pregunta no aplica. */
  preflight: PreflightState
  /**
   * Campo que el usuario pidió enfocar desde un aviso del preflight: el `path` **crudo** del
   * desajuste, tal como lo emite el motor. La traducción a `id` de control la resuelve quien
   * atiende el pedido (`App`), porque un path puede corresponder a más de un `id` candidato.
   * Vive en el store porque quien lo pide (el aviso en Datos) y quien lo atiende están en
   * pestañas distintas.
   */
  focusField: string | null
  setFocusField: Dispatch<SetStateAction<string | null>>
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
  const [job, setJob] = useState<Job | null>(null)
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [seed, setSeed] = useState<SeedState | null>(null)
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [externalInputs, setExternalInputs] = useState<
    Record<string, ExternalInput>
  >({})
  const [selectedDataset, setSelectedDataset] =
    useState<SelectedDataset | null>(null)
  const [validation, setValidation] = useState<ValidationState>({ kind: "idle" })
  const [lastRun, setLastRun] = useState<LastRun | null>(null)
  const [results, setResults] = useState<ResultsResponse | null>(null)
  const [welcomeDismissed, setWelcomeDismissed] = useState(false)
  const [preflight, setPreflight] = useState<PreflightState>({ kind: "idle" })
  const [focusField, setFocusField] = useState<string | null>(null)
  const requiredExternals = useMemo(
    () => requiredExternalArtifacts(job, config),
    [job, config],
  )
  const externalRefs = useMemo(
    () => buildExternalRefs(requiredExternals, externalInputs),
    [requiredExternals, externalInputs],
  )
  // Los efectos de abajo NO dependen de `externalRefs` por identidad de objeto —cambiaría en cada
  // render— sino de su forma serializada: dos peticiones con los mismos insumos no tienen por qué
  // volver a preguntar. Mismo criterio que el `configRef` de la validación.
  const externalKey = JSON.stringify(externalRefs)
  const externalRefsRef = useRef(externalRefs)
  externalRefsRef.current = externalRefs
  const requestSeq = useRef(0)
  const preflightSeq = useRef(0)
  // Último config renderizado, para que el preflight NO dependa de `config` como disparador (ver
  // su efecto). Asignar en el cuerpo del render es el patrón de «ref al último valor».
  const configRef = useRef(config)
  configRef.current = config

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
      void validateConfig(config, externalRefsRef.current)
        .then((res) => {
          if (seq !== requestSeq.current) return // respuesta obsoleta
          if (res.valid && res.config_hash) {
            // `pipeline` puede faltar si el backend es anterior a la enmienda
            // VALIDACION-PIPELINE (o es un fixture viejo): se trata como "sin información", que
            // es lo que era antes, y no como "inejecutable" — un aviso inventado es peor que
            // ninguno.
            setValidation({
              kind: "valid",
              hash: res.config_hash,
              pipeline: res.pipeline ?? null,
              producedColumns: res.produced_columns_by_section ?? {},
            })
          } else {
            // El schema se pasa para elidir el tag de las uniones discriminadas (D-VIS-7): sin él,
            // las 58 hojas bajo una rama no casan con ningún control. Aquí nunca es `null` —el
            // efecto arranca con `if (schema === null) return`—, pero el parámetro es opcional y
            // omitirlo sólo devuelve el comportamiento anterior.
            setValidation({
              kind: "invalid",
              count: res.errors.length,
              lookup: buildErrorLookup(
                res.errors,
                schema.payload.json_schema,
                schema.payload.json_schema.$defs ?? {},
              ),
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

  // Preflight config↔dataset (enmienda PREFLIGHT-DATASET, D-PRE-1): compara lo que el config
  // NOMBRA contra las columnas que el dataset TRAE, sin correr nada y sin leer los datos. Va
  // ENCADENADO detrás de la validación —sólo dispara con un `config_hash` en mano— por tres
  // razones medidas: (1) `/api/preflight` NO responde siempre 200 como `/api/validate`: da 422 si
  // el config no reconstruye, y encadenarlo vuelve inalcanzable ese 422; (2) el hash sólo cambia
  // cuando cambia el config de verdad, así que hereda el debounce de la validación sin sumar uno
  // propio; (3) sobre un config roto, un aviso de columnas sería ruido encima del error que el
  // usuario ya tiene delante.
  const validHash = validation.kind === "valid" ? validation.hash : null
  useEffect(() => {
    // La demo estática no tiene backend que materialice un dataset, y sirve corridas reales ya
    // compatibles por construcción: preguntar sólo produciría un fallo de red y un aviso falso.
    if (DEMO_MODE) return
    if (validHash === null || datasetId === null || datasetId === "") {
      setPreflight({ kind: "idle" })
      return
    }
    const seq = ++preflightSeq.current
    setPreflight({ kind: "checking" })
    void preflightDataset(configRef.current, datasetId, externalRefsRef.current)
      .then((res) => {
        if (seq !== preflightSeq.current) return // respuesta obsoleta
        // Los desajustes del insumo externo llegan en su propia lista (D-PUE-8) y se muestran por
        // el mismo canal: necesitan exactamente lo mismo —un mensaje que leer y, cuando anclan a
        // un campo, una ruta a la que saltar—. Los que no anclan a ningún campo viajan con
        // `path: null`, y el aviso los pinta sin botón de salto.
        const externos = res.external_mismatches ?? []
        setPreflight(
          res.compatible && externos.length === 0
            ? { kind: "ok" }
            : {
                kind: "issues",
                mismatches: res.mismatches,
                uninspected: res.uninspected,
                external: externos,
              },
        )
      })
      .catch(() => {
        if (seq !== preflightSeq.current) return
        setPreflight({ kind: "unreachable" }) // degrada suave; NO inventa veredicto
      })
    // ⚠️ `config` NO va en las dependencias, y no es un olvido: es la corrección de una carrera
    // medida en vivo. Con él, editar disparaba el preflight en el MISMO render en que `config` ya
    // era el nuevo pero `validation` todavía traía el hash del anterior — se enviaba un config sin
    // validar y el endpoint respondía 422. El hash es la identidad del config **ya validado**: si
    // el usuario sigue tecleando, la validación vuelve a `checking`, el hash desaparece y esto no
    // corre; cuando reaparece, `configRef.current` es exactamente el config que lo produjo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [validHash, datasetId, externalKey])

  // Los setters de useState son estables → el value solo cambia con el estado real.
  const value = useMemo<AppState>(
    () => ({
      schema,
      job,
      setJob,
      config,
      setConfig,
      seed,
      setSeed,
      datasetId,
      setDatasetId,
      externalInputs,
      setExternalInputs,
      requiredExternals,
      externalRefs,
      selectedDataset,
      setSelectedDataset,
      validation,
      setValidation,
      preflight,
      focusField,
      setFocusField,
      lastRun,
      setLastRun,
      results,
      setResults,
      welcomeDismissed,
      setWelcomeDismissed,
    }),
    [
      schema,
      job,
      config,
      seed,
      datasetId,
      externalInputs,
      requiredExternals,
      externalRefs,
      selectedDataset,
      validation,
      preflight,
      focusField,
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
