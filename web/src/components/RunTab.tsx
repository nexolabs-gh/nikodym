import { useEffect, useState } from "react"
import {
  ArrowRight,
  CircleAlert,
  CircleCheck,
  Database,
  Loader2,
  Play,
  TriangleAlert,
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
import {
  configEditadoRespectoDelPreset,
  configFingerprint,
} from "@/lib/bootstrap"
import {
  jobSwitchForConfig,
  jobSwitchNotice,
  loadJobs,
  type Job,
  type JobSwitch,
} from "@/lib/jobs"
import { presetDisplay } from "@/lib/presentation"
import { runHint } from "@/lib/preflight"
import { canRun, describeApiError } from "@/lib/validation"
import { useAppState, type AppState } from "@/state/appStore"

/** Lo que se lee en el selector de ejemplos mientras no hay ninguno cargado. */
const PLACEHOLDER_EJEMPLO = "Elige un ejemplo…"

/**
 * Dependencias del cambio de preset (SDD-28), inyectadas para poder ejercitar el flujo sin montar
 * React (mismo patrón que `bootstrapWorkspace`): la API que trae el preset y los setters del store
 * que se resiembran o se LIMPIAN. `resetOutcome` limpia el estado local de la corrida en Ejecutar;
 * al entrar desde el landing ese estado aún no existe (RunTab monta en idle), así que allí es no-op.
 */
export interface PresetSwitchDeps {
  getPreset: (presetId: string) => Promise<PresetResponse>
  /**
   * Catálogo con el que se resuelve a qué trabajo corresponde el ejemplo (D-JOB-17). Nunca lanza
   * —cae al fixture bundleado—, así que un backend caído no deja el ejemplo sin trabajo.
   */
  loadJobs: () => Promise<Job[]>
  setConfig: AppState["setConfig"]
  setJob: AppState["setJob"]
  setDatasetId: AppState["setDatasetId"]
  setSelectedDataset: AppState["setSelectedDataset"]
  setSeed: AppState["setSeed"]
  setResults: AppState["setResults"]
  setLastRun: AppState["setLastRun"]
  resetOutcome: () => void
}

/**
 * Resiembra el config y el dataset recomendado del preset elegido, **deja la sesión en el trabajo
 * que ese ejemplo trae** (D-JOB-17) y CORTA con la corrida anterior (results / lastRun / outcome).
 *
 * 🔴 **El trabajo se mueve por la misma regla que el YAML, y por el mismo motivo.** Entrar por «Ver
 * un ejemplo» de scorecard estando en IFRS 9 dejaba un config de scorecard bajo el sidebar de
 * IFRS 9: las secciones del ejemplo no tenían pestaña y las que se veían estaban apagadas en él —
 * justo el estado que D-JOB-1 existe para impedir—. Un ejemplo es un config traído de fuera igual
 * que un archivo, así que se resuelve con `jobSwitchForConfig` y no con un mecanismo paralelo.
 *
 * ⚠️ **La demo estática entra por aquí y también cambia de trabajo** (decisión explícita al cerrar
 * este hueco, por encima del «`job === null` a propósito» de D-JOB-19). Medido sobre los tres
 * ejemplos que publica el backend: el scorecard pasa a mostrar 9 secciones de 14 y el de IFRS 9, 4;
 * el de provisiones no calza con ningún trabajo y **sigue mostrando las 14**. Las secciones que
 * desaparecen son exactamente las que ese ejemplo trae apagadas, así que el escaparate no pierde
 * nada que el usuario pudiera ver: pierde pestañas vacías.
 *
 * Sin ese corte de la corrida (bug P0): tras ejecutar un dominio y cambiar a otro sin re-ejecutar,
 * Resultados y Reporte seguían mostrando el dominio VIEJO con lineage mixto y la tarjeta "Corrida
 * completada" conservaba el outcome anterior. Lógica pura (sin React): los efectos van por `deps`,
 * así el flujo completo se prueba sin DOM. La usan `RunTab.handlePreset` (selector in-workspace),
 * `App.enterDemo` (selector del landing) y `ConfigTab.handleLoadPreset` («Ver un ejemplo»).
 *
 * Un fallo del backend se propaga **sin escribir nada**: el config vigente y su trabajo siguen
 * siendo coherentes entre sí.
 */
export async function applyPreset(
  presetId: string,
  jobActivo: Job | null,
  deps: PresetSwitchDeps,
): Promise<JobSwitch> {
  const preset = await deps.getPreset(presetId)
  const jobs = await deps.loadJobs()
  const cambio = jobSwitchForConfig(jobs, preset.config, jobActivo)
  deps.setConfig(structuredClone(preset.config))
  // Sólo si cambia: el catálogo se vuelve a pedir en cada llamada, así que reescribirlo siempre
  // metería en el store un objeto nuevo equivalente al que ya había y forzaría un render de más.
  if (cambio.cambia) deps.setJob(cambio.job)
  deps.setDatasetId(preset.dataset_id)
  deps.setSelectedDataset(null)
  deps.setSeed({
    kind: "preset",
    name: preset.name,
    datasetId: preset.dataset_id,
    // La huella de lo recién sembrado: a partir de aquí, cualquier diferencia es edición del
    // usuario, y el selector deja de poder afirmar que el config «es» este preset.
    fingerprint: configFingerprint(preset.config),
  })
  // Corte con la corrida previa: su dominio ya no aplica al preset recién sembrado.
  deps.setResults(null)
  deps.setLastRun(null)
  deps.resetOutcome()
  return cambio
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
    preflight,
    seed,
    job,
    setJob,
    setConfig,
    setDatasetId,
    setSelectedDataset,
    setSeed,
    setLastRun,
    setResults,
    externalRefs,
  } = useAppState()
  const [outcome, setOutcome] = useState<RunOutcome>({ kind: "idle" })
  // Catálogo de presets (SDD-28): se puebla desde `GET /api/config/presets`. `switching` bloquea
  // el selector mientras se resiembra el config/dataset del preset elegido.
  const [presets, setPresets] = useState<PresetSummary[]>([])
  const [switching, setSwitching] = useState(false)
  // Qué trabajo eligió el ejemplo recién cargado, cuando cambió el de la sesión (D-JOB-17). Estado
  // LOCAL, igual que el gemelo de `ConfigTab`: nace y muere con esta pantalla, y el sidebar —que es
  // lo que el aviso explica— ya cambió a la vista.
  const [jobNotice, setJobNotice] = useState<string | null>(null)
  // Preset al que se quiere cambiar teniendo el config editado: espera confirmación (ver §M5).
  const [confirmar, setConfirmar] = useState<PresetSummary | null>(null)

  const gate = canRun(validation, datasetId)
  // Aviso del preflight (D-PRE-5): cambia el ASPECTO del botón y pone la advertencia al lado, pero
  // NO toca `disabled`. Informar no es bloquear: la corrida sigue siendo la autoridad sobre sí
  // misma, y quitarle al usuario la posibilidad de intentar sería peor que un aviso que sobre.
  const hint = runHint(preflight)
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

  // ¿El config sigue siendo el que sembró ese preset, o el usuario lo trabajó? Decide dos cosas:
  // que el selector no afirme algo falso, y que cambiar de preset pida confirmación en vez de
  // borrar el trabajo de un click (medido en el ensayo del webinar: tras corregir 19 desajustes a
  // mano, el selector seguía diciendo `f1-estandar-consumo` y tocarlo resembraba sin avisar).
  const editado = configEditadoRespectoDelPreset(seed, config)

  /** Puerta del selector: con el config editado no se cambia de preset sin confirmar. */
  async function pedirCambioDePreset(presetId: string) {
    if (switching || running) return
    if (presetId === activePreset?.id) return
    const destino = presets.find((p) => p.id === presetId) ?? null
    if (editado && destino !== null) {
      setConfirmar(destino)
      return
    }
    await handlePreset(presetId)
  }

  // Cambia de preset: pide su detalle (`GET /api/config/preset/{id}`), RESIEMBRA el config y su
  // dataset recomendado (el provider revalida solo al cambiar el config), reinicia el preview del
  // dataset y CORTA con la corrida anterior (results/lastRun/outcome) vía `applyPreset`, para que
  // Resultados/Reporte/tarjeta no sigan mostrando el dominio viejo. Falla en silencio: el selector
  // nunca rompe la app; si el detalle no llega, el preset vigente (y su corrida) siguen intactos.
  async function handlePreset(presetId: string) {
    if (switching || running) return
    setSwitching(true)
    setJobNotice(null) // el aviso hablaba del ejemplo anterior
    try {
      const cambio = await applyPreset(presetId, job, {
        getPreset: getPresetById,
        loadJobs,
        setConfig,
        setJob,
        setDatasetId,
        setSelectedDataset,
        setSeed,
        setResults,
        setLastRun,
        resetOutcome: () => setOutcome({ kind: "idle" }),
      })
      // El sidebar se acaba de reescribir y esta pestaña no es la que cambió: sin decirlo, el
      // usuario vuelve a Configuración y encuentra otro menú sin saber por qué (D-JOB-17).
      setJobNotice(jobSwitchNotice(cambio, "ejemplo"))
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
      // Los insumos externos van con la corrida (D-PUE-3): el archivo ya está subido, así que lo
      // que viaja es su referencia. Se derivan de lo que el trabajo PIDE, no de lo que quedó
      // subido, para no mandar un archivo que el backend declararía inerte.
      const run = await runPipeline(config, datasetId, externalRefs)
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
              <p className="text-sm font-medium text-eyebrow">Ejemplos</p>
              <p className="text-xs text-muted-foreground">
                Pipelines completos con datos de muestra. Elegir uno reemplaza tu
                config y tu dataset por los suyos.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-64">
                <Select
                  value={activePreset?.id ?? undefined}
                  onValueChange={(v) => {
                    if (v) void pedirCambioDePreset(v)
                  }}
                  disabled={switching || running}
                >
                  <SelectTrigger className="w-full" aria-label="Ejemplo a cargar">
                    {/*
                     * `Select.Value` pinta el VALOR crudo, no el texto del `<SelectItem>`: sin esta
                     * función el control leía `f3-provisiones-consumo`. Es la tercera vez que este
                     * repo paga la misma trampa (`__por_orden__` en ExternalInputCard, y el
                     * selector de partición de ResultsTab), y por eso ahora hay un gate.
                     * ⚠️ Con `children` función el `placeholder` se IGNORA —medido en el fuente de
                     * @base-ui/react—, así que el caso sin selección lo cubre la propia función.
                     */}
                    <SelectValue>
                      {(value) => {
                        const elegido = presets.find((p) => p.id === value)
                        return elegido ? presetDisplay(elegido).title : PLACEHOLDER_EJEMPLO
                      }}
                    </SelectValue>
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
              {editado ? (
                <span className="rounded-md border border-eyebrow/40 bg-eyebrow/10 px-2 py-0.5 text-xs text-eyebrow">
                  con tus cambios
                </span>
              ) : null}
              {switching ? (
                <Loader2
                  className="size-4 animate-spin text-muted-foreground"
                  aria-hidden="true"
                />
              ) : null}
            </div>
            {/* El selector no puede afirmar «f1-estandar-consumo» a secas sobre un config que el
                usuario ya editó campo por campo: lo que se va a correr es SU config, no el del
                preset. Y como cambiar de preset lo descarta, se avisa antes, no después. */}
            {editado ? (
              <p className="text-xs leading-relaxed text-muted-foreground">
                Partiste de este preset y lo ajustaste: la corrida usará{" "}
                <strong className="text-foreground/90">tu configuración</strong>, no
                la de fábrica. Elegir un preset aquí descarta esos cambios.
              </p>
            ) : activePreset ? (
              <p className="text-xs leading-relaxed text-muted-foreground">
                {presetDisplay(activePreset).blurb}
              </p>
            ) : null}
            {/* El ejemplo cargado cambió el trabajo de la sesión (D-JOB-17). No es un error ni algo
                que corregir: es la explicación de por qué el menú de la izquierda acaba de cambiar,
                y por eso se pinta en tono neutro y con `aria-live` — el sidebar cambia fuera de la
                vista de quien usa lector de pantalla, y encima desde OTRA pestaña. */}
            {jobNotice ? (
              <p
                role="status"
                aria-live="polite"
                className="flex items-start gap-2 rounded-lg border border-brand-cyan/25 bg-brand-cyan/5 px-3 py-2 text-xs text-muted-foreground"
              >
                <CircleCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                <span>{jobNotice}</span>
              </p>
            ) : null}
            {/* Confirmación: resembrar borra el trabajo del formulario y no hay deshacer. */}
            {confirmar ? (
              <div className="space-y-2 rounded-lg border border-eyebrow/40 bg-eyebrow/5 p-3">
                <p className="text-xs leading-relaxed text-foreground/90">
                  Cambiar a{" "}
                  <strong>{presetDisplay(confirmar).title}</strong> descarta la
                  configuración que editaste y siembra la de fábrica, junto con su
                  dataset recomendado. No se puede deshacer.
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      const destino = confirmar.id
                      setConfirmar(null)
                      void handlePreset(destino)
                    }}
                  >
                    Descartar mis cambios y cambiar
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setConfirmar(null)}
                  >
                    Seguir con mi configuración
                  </Button>
                </div>
              </div>
            ) : null}
            {/* De dónde viene el config cuando NO es un preset. El selector vacío ya no miente,
                pero por sí solo tampoco explica nada; y elegir un preset aquí reemplaza lo que el
                usuario trajo, así que conviene decirlo ANTES de que lo descubra perdiéndolo. */}
            {seed !== null && seed.kind !== "preset" ? (
              <p className="text-xs leading-relaxed text-muted-foreground">
                {seed.kind === "yaml"
                  ? `El config activo viene de «${seed.fileName}», no de un ejemplo. Elegir uno aquí lo reemplaza.`
                  : seed.kind === "job"
                    ? `Estás en «${seed.label}», con tu propio config. Elegir un ejemplo aquí lo reemplaza por el suyo.`
                    : seed.kind === "empty"
                    ? // `empty` NO es «no viene de un preset»: es que todavía no hay nada. Reusar el
                      // texto genérico dejaba la primera pantalla de Ejecutar explicando un config
                      // que el usuario nunca cargó.
                      "Todavía no has cargado ninguna configuración. Elegir un ejemplo aquí carga uno completo con su dataset de muestra."
                    : "El config activo no viene de un ejemplo. Elegir uno aquí lo reemplaza."}
              </p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {/* Controles: botón primario + gate (SDD §8). */}
      <Card className="shadow-card">
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            {/* `disabled` NO mira el preflight: sólo el gate de siempre (config válido + dataset).
                Lo único que cambia con un desajuste es el aspecto y el texto. */}
            <Button
              onClick={handleRun}
              disabled={!gate.ok || running}
              variant={hint !== null && !preparing ? "outline" : "default"}
            >
              {running || preparing ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <Play aria-hidden="true" />
              )}
              {preparing
                ? "Cargando configuración…"
                : hint !== null
                  ? "Ejecutar de todos modos"
                  : "Ejecutar corrida"}
            </Button>
            {gate.ok && hint !== null ? (
              <p className="inline-flex max-w-md items-start gap-1.5 text-xs text-amber-200/90">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                {hint}
              </p>
            ) : gate.ok ? (
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
              // ⚠️ Las tres ramas existen porque las dos anteriores AFIRMABAN «el config estándar ya
              // está cargado y validado» — cierto mientras la sesión arrancaba sembrada, falso desde
              // D-JOB-2 y visible en la primera pantalla de Ejecutar. Ningún test lo habría cazado:
              // el copy de un `EmptyState` no lo asevera nadie.
              description={
                seed?.kind === "job"
                  ? "Este trabajo ya tiene sus secciones cargadas: trae tu dataset y completa en Configuración lo que sólo puedes decidir tú."
                  : seed?.kind === "empty"
                    ? "Todavía no hay nada que correr: trae tu dataset y activa en Configuración las secciones del pipeline que necesitas."
                    : datasetId === null
                    ? "El config ya está cargado y validado. Solo falta elegir el dataset con el que quieres correr el pipeline."
                    : "La configuración ya está lista: dispara la corrida para ver aquí su estado y su lineage."
              }
              tag="Ejecutar"
              // Sin dataset el botón de arriba no abre: el CTA lleva al paso que falta.
              action={
                datasetId === null
                  ? {
                      label: seed?.kind === "empty" ? "Traer mi dataset" : "Elegir dataset",
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
