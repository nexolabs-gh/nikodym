import { useEffect, useState } from "react"
import {
  ArrowRight,
  CircleAlert,
  CircleCheck,
  Database,
  Loader2,
  Play,
} from "lucide-react"

import { EmptyState } from "@/components/EmptyState"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  ApiError,
  getPresetById,
  getResults,
  listPresets,
  runPipeline,
  type PresetResponse,
  type PresetSummary,
  type RunStatus,
} from "@/lib/api"
import { presetDisplay } from "@/lib/presentation"
import { canRun, describeApiError } from "@/lib/validation"
import { useAppState, type AppState } from "@/state/appStore"

/**
 * Dependencias del cambio de preset (SDD-28), inyectadas para poder ejercitar el flujo sin montar
 * React (mismo patrón que `bootstrapWorkspace`): la API que trae el preset y los setters del store
 * que se resiembran o se LIMPIAN. `resetOutcome` limpia el estado local de la corrida en Ejecutar;
 * al entrar desde el landing ese estado aún no existe (RunTab monta en idle), así que allí es no-op.
 */
export interface PresetSwitchDeps {
  getPreset: (presetId: string) => Promise<PresetResponse>
  setConfig: AppState["setConfig"]
  setDatasetId: AppState["setDatasetId"]
  setSelectedDataset: AppState["setSelectedDataset"]
  setSeed: AppState["setSeed"]
  setResults: AppState["setResults"]
  setLastRun: AppState["setLastRun"]
  resetOutcome: () => void
}

/**
 * Resiembra el config y el dataset recomendado del preset elegido y CORTA con la corrida anterior
 * (results / lastRun / outcome). Sin ese corte (bug P0): tras ejecutar un dominio y cambiar a otro
 * sin re-ejecutar, Resultados y Reporte seguían mostrando el dominio VIEJO con lineage mixto y la
 * tarjeta "Corrida completada" conservaba el outcome anterior. Lógica pura (sin React): los efectos
 * van por `deps`, así el flujo completo (incluido el corte) se prueba sin DOM. La usan tanto
 * `RunTab.handlePreset` (selector in-workspace) como `App.enterDemo` (selector del landing).
 */
export async function applyPreset(
  presetId: string,
  deps: PresetSwitchDeps,
): Promise<void> {
  const preset = await deps.getPreset(presetId)
  deps.setConfig(structuredClone(preset.config))
  deps.setDatasetId(preset.dataset_id)
  deps.setSelectedDataset(null)
  deps.setSeed({ kind: "preset", name: preset.name, datasetId: preset.dataset_id })
  // Corte con la corrida previa: su dominio ya no aplica al preset recién sembrado.
  deps.setResults(null)
  deps.setLastRun(null)
  deps.resetOutcome()
}

interface RunTabProps {
  /** Navega a otra sección del shell (la navegación vive en App, no en el store). */
  onNavigate: (section: string) => void
}

/**
 * Resultado de disparar la corrida en el front (NO es el resultado de dominio): `done`
 * incluye el `status` real (done/failed) que devolvió el backend; `error` es un fallo de
 * app (ApiError) al no poder disparar. `status:"failed"` cae en `done`, es un RESULTADO válido.
 */
type RunOutcome =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "done"; runId: string; status: RunStatus; error?: string }
  | { kind: "error"; message: string }

/** Mensaje legible de un fallo al disparar la corrida: detalle del backend (422/404) o el error crudo. */
function runErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return describeApiError(err.body, err.message)
  }
  return err instanceof Error ? err.message : String(err)
}

/**
 * Pestaña Ejecutar (SDD-23 §7.4 / §8): DISPARA la corrida y muestra estado + lineage.
 * Cero lógica de dominio (§1): solo llama la API y transporta lo que devuelve. No grafica
 * ni formatea artefactos (eso es Resultados). La corrida es SÍNCRONA: `POST /api/run`
 * devuelve `{run_id,status}` ya terminado; luego se encadena `GET /api/results` para dejar
 * el JSON en el store. `status:"failed"` NO es error HTTP: llega 200 con results parcial + `error`.
 */
export function RunTab({ onNavigate }: RunTabProps) {
  const {
    config,
    datasetId,
    validation,
    seed,
    setConfig,
    setDatasetId,
    setSelectedDataset,
    setSeed,
    setLastRun,
    setResults,
  } = useAppState()
  const [outcome, setOutcome] = useState<RunOutcome>({ kind: "idle" })
  // Catálogo de presets (SDD-28): se puebla desde `GET /api/config/presets`. `switching` bloquea
  // el selector mientras se resiembra el config/dataset del preset elegido.
  const [presets, setPresets] = useState<PresetSummary[]>([])
  const [switching, setSwitching] = useState(false)

  const gate = canRun(validation, datasetId)
  const running = outcome.kind === "running"
  const configHash = validation.kind === "valid" ? validation.hash : null
  // El arranque de la sesión (provider) siembra y valida el preset solo: mientras no termina
  // (`seed === null`) el botón espera, y se habilita sin que el usuario configure nada (UX1).
  const preparing = seed === null

  // Carga del catálogo de presets al montar (una vez). Falla en silencio: sin catálogo el
  // selector no se muestra y el flujo estándar (preset ya sembrado por el provider) sigue igual.
  useEffect(() => {
    let alive = true
    void listPresets()
      .then((res) => {
        if (alive) setPresets(res.presets)
      })
      .catch(() => {
        /* backend caído: sin selector, el preset sembrado al arranque basta. */
      })
    return () => {
      alive = false
    }
  }, [])

  // Preset activo: se casa el `seed` (que guarda el NOMBRE del preset sembrado) contra el catálogo.
  const activePreset =
    seed?.kind === "preset"
      ? (presets.find((p) => p.name === seed.name) ?? null)
      : null

  // Cambia de preset: pide su detalle (`GET /api/config/preset/{id}`), RESIEMBRA el config y su
  // dataset recomendado (el provider revalida solo al cambiar el config), reinicia el preview del
  // dataset y CORTA con la corrida anterior (results/lastRun/outcome) vía `applyPreset`, para que
  // Resultados/Reporte/tarjeta no sigan mostrando el dominio viejo. Falla en silencio: el selector
  // nunca rompe la app; si el detalle no llega, el preset vigente (y su corrida) siguen intactos.
  async function handlePreset(presetId: string) {
    if (switching || running) return
    setSwitching(true)
    try {
      await applyPreset(presetId, {
        getPreset: getPresetById,
        setConfig,
        setDatasetId,
        setSelectedDataset,
        setSeed,
        setResults,
        setLastRun,
        resetOutcome: () => setOutcome({ kind: "idle" }),
      })
    } catch {
      /* no se pudo cambiar de preset: el actual sigue vigente; el usuario puede reintentar. */
    } finally {
      setSwitching(false)
    }
  }

  async function handleRun() {
    if (!gate.ok || datasetId === null) return // guard (el botón ya está deshabilitado)
    setOutcome({ kind: "running" })
    try {
      const run = await runPipeline(config, datasetId)
      setLastRun({ runId: run.run_id, status: run.status })
      // Encadena los artefactos al store (los consume Resultados). Si `status:"failed"`,
      // el mensaje sale del campo `error` del results parcial (no es error de app).
      let runError: string | undefined
      try {
        const results = await getResults(run.run_id)
        setResults(results)
        if (typeof results.error === "string") runError = results.error
      } catch {
        // La corrida existe aunque no podamos traer sus artefactos; no rompe la app.
      }
      setOutcome({
        kind: "done",
        runId: run.run_id,
        status: run.status,
        error: runError,
      })
    } catch (err) {
      // ApiError (422 config inválido / 404 dataset o run desconocido) → inline + reintento.
      setOutcome({ kind: "error", message: runErrorMessage(err) })
    }
  }

  return (
    <div className="space-y-6">
      {/* Selector de preset (SDD-28): elige QUÉ pipeline correr. Al cambiarlo se resiembra el
          config y su dataset. Se muestra solo si el catálogo cargó (backend disponible). */}
      {presets.length > 0 ? (
        <Card className="shadow-card">
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <p className="text-sm font-medium text-eyebrow">Preset</p>
              <p className="text-xs text-muted-foreground">
                Elige el pipeline a correr. Al cambiarlo se resiembra el config
                y su dataset recomendado.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-64">
                <Select
                  value={activePreset?.id ?? undefined}
                  onValueChange={(v) => {
                    if (v) void handlePreset(v)
                  }}
                  disabled={switching || running}
                >
                  <SelectTrigger className="w-full" aria-label="Preset a correr">
                    <SelectValue placeholder="Elige un preset…" />
                  </SelectTrigger>
                  <SelectContent>
                    {presets.map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {presetDisplay(p).title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {switching ? (
                <Loader2
                  className="size-4 animate-spin text-muted-foreground"
                  aria-hidden="true"
                />
              ) : null}
            </div>
            {activePreset ? (
              <p className="text-xs leading-relaxed text-muted-foreground">
                {presetDisplay(activePreset).blurb}
              </p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {/* Controles: botón primario + gate (SDD §8). */}
      <Card className="shadow-card">
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={handleRun} disabled={!gate.ok || running}>
              {running || preparing ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <Play aria-hidden="true" />
              )}
              {preparing ? "Cargando configuración…" : "Ejecutar corrida"}
            </Button>
            {gate.ok ? (
              <p className="text-xs text-muted-foreground">
                Config válido · dataset{" "}
                <span className="font-mono text-muted-foreground">{datasetId}</span>
              </p>
            ) : preparing ? null : (
              <p className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                <CircleAlert className="size-3.5" aria-hidden="true" />
                {gate.reason}
              </p>
            )}
          </div>
          <p className="text-xs leading-relaxed text-muted-foreground">
            La corrida es síncrona (
            <span className="font-mono">nikodym.run</span>): dispara el pipeline
            y devuelve su estado. Los artefactos se ven en Resultados.
          </p>
        </CardContent>
      </Card>

      {/* Estado / resultado de la corrida (aria-live: lo anuncia al terminar). */}
      <div role="status" aria-live="polite">
        {outcome.kind === "idle" ? (
          <Card className="shadow-card">
            <EmptyState
              icon={Play}
              title="Sin corridas todavía"
              description={
                datasetId === null
                  ? "El config estándar ya está cargado y validado. Solo falta elegir el dataset con el que quieres correr el pipeline."
                  : "La configuración estándar ya está lista: dispara la corrida para ver aquí su estado y su lineage."
              }
              tag="Ejecutar"
              // Sin dataset el botón de arriba no abre: el CTA lleva al paso que falta.
              action={
                datasetId === null
                  ? {
                      label: "Elegir dataset",
                      onClick: () => onNavigate("datos"),
                      icon: Database,
                    }
                  : undefined
              }
            />
          </Card>
        ) : outcome.kind === "running" ? (
          <Card className="shadow-card">
            <CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              Ejecutando la corrida…
            </CardContent>
          </Card>
        ) : outcome.kind === "error" ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-xs text-destructive">
            <p className="flex items-center gap-1.5 font-medium">
              <CircleAlert className="size-3.5" aria-hidden="true" />
              No se pudo ejecutar la corrida
            </p>
            <p className="mt-1 text-destructive/90">{outcome.message}</p>
            <p className="mt-1 text-muted-foreground">
              Ajusta el config o el dataset y reintenta.
            </p>
          </div>
        ) : (
          <RunResult
            runId={outcome.runId}
            status={outcome.status}
            error={outcome.error}
            configHash={configHash}
            datasetId={datasetId}
            onGoToResults={() => onNavigate("resultados")}
          />
        )}
      </div>
    </div>
  )
}

interface RunResultProps {
  runId: string
  status: RunStatus
  error?: string
  configHash: string | null
  datasetId: string | null
  onGoToResults: () => void
}

/** Tarjeta de la corrida terminada: done/failed + lineage (run_id/config_hash/dataset) + CTA a Resultados. */
function RunResult({
  runId,
  status,
  error,
  configHash,
  datasetId,
  onGoToResults,
}: RunResultProps) {
  const done = status === "done"
  return (
    <Card className="shadow-card">
      <CardContent className="space-y-4">
        <div className="text-sm font-medium">
          {done ? (
            <span className="inline-flex items-center gap-1.5 text-eyebrow">
              <CircleCheck className="size-4" aria-hidden="true" />
              Corrida completada
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-amber-200/90">
              <CircleAlert className="size-4" aria-hidden="true" />
              La corrida terminó con fallo
            </span>
          )}
        </div>

        {/* Lineage de la corrida (identidad reproducible; sin cálculo propio). */}
        <dl className="grid gap-1.5 font-mono text-xs text-muted-foreground">
          <div className="flex justify-between gap-3">
            <dt className="shrink-0 text-muted-foreground">run_id</dt>
            <dd className="min-w-0 truncate text-right" title={runId}>
              {runId}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="shrink-0 text-muted-foreground">config_hash</dt>
            <dd
              className="min-w-0 truncate text-right"
              title={configHash ?? undefined}
            >
              {configHash ?? "—"}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="shrink-0 text-muted-foreground">dataset</dt>
            <dd
              className="min-w-0 truncate text-right"
              title={datasetId ?? undefined}
            >
              {datasetId ?? "—"}
            </dd>
          </div>
        </dl>

        {/* status:"failed" es un RESULTADO válido: se muestra el mensaje `error` del results parcial. */}
        {!done && error ? (
          <div className="rounded-lg border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200/90">
            {error}
          </div>
        ) : null}

        <div>
          <Button variant="outline" size="sm" onClick={onGoToResults}>
            Ver resultados
            <ArrowRight aria-hidden="true" />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
