import { useState } from "react"
import {
  ArrowRight,
  CircleAlert,
  CircleCheck,
  Loader2,
  Play,
} from "lucide-react"

import { EmptyState } from "@/components/EmptyState"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { ApiError, getResults, runPipeline, type RunStatus } from "@/lib/api"
import { canRun, describeApiError } from "@/lib/validation"
import { useAppState } from "@/state/appStore"

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
  const { config, datasetId, validation, setLastRun, setResults } =
    useAppState()
  const [outcome, setOutcome] = useState<RunOutcome>({ kind: "idle" })

  const gate = canRun(validation, datasetId)
  const running = outcome.kind === "running"
  const configHash = validation.kind === "valid" ? validation.hash : null

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
      {/* Controles: botón primario + gate (SDD §8). */}
      <Card className="shadow-card">
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={handleRun} disabled={!gate.ok || running}>
              {running ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <Play aria-hidden="true" />
              )}
              Ejecutar corrida
            </Button>
            {gate.ok ? (
              <p className="text-xs text-muted-foreground">
                Config válido · dataset{" "}
                <span className="font-mono text-muted-foreground">{datasetId}</span>
              </p>
            ) : (
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
              description="Con un config válido y un dataset elegido, dispara la corrida para ver aquí su estado y su lineage."
              tag="Ejecutar"
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
