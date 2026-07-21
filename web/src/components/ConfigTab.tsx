import { useCallback, useRef, useState } from "react"
import {
  CircleAlert,
  CircleCheck,
  CloudOff,
  Download,
  FilePlus2,
  Loader2,
  Sparkles,
  Upload,
} from "lucide-react"

import { FieldRenderer } from "@/components/FieldRenderer"
import { applyPreset } from "@/components/RunTab"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { Button } from "@/components/ui/button"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ApiError, configFromYaml, configToYaml, getPreset } from "@/lib/api"
import type { SeedState } from "@/lib/bootstrap"
import { type Path, getAtPath, setAtPath } from "@/lib/config-store"
import { DEMO_MODE } from "@/lib/demo"
import {
  type Defs,
  type JsonSchema,
  groupedFields,
  resolveRef,
} from "@/lib/form-engine"
import {
  F1_SECTIONS,
  type SchemaSource,
  isRenderableSection,
} from "@/lib/schema"
import { type ValidationState, describeApiError } from "@/lib/validation"
import { useAppState } from "@/state/appStore"

const SOURCE_BANNER: Record<
  SchemaSource,
  { tone: "ok" | "warn"; text: string }
> = {
  backend: {
    tone: "ok",
    // En la demo pública NO hay backend: `loadSchema` marca la fuente como "backend" para que el
    // editor no se vea degradado (schema.ts §DEMO_MODE), así que el texto de esa rama se leería
    // como una afirmación falsa —«en vivo desde /api/schema»— en una página estática. Se dice la
    // verdad sin rebajar el tono: el schema es el mismo que publicó el backend, capturado.
    text: DEMO_MODE
      ? "Schema capturado del backend en una corrida real; esta demo no ejecuta cálculo en el navegador."
      : "Schema en vivo desde el backend (/api/schema).",
  },
  "fixture-opaque": {
    tone: "warn",
    text: "El backend devolvió una sección F1 sin expandir (inesperado desde B23.4c, que ya materializa el schema completo); usando el snapshot local como respaldo.",
  },
  "fixture-offline": {
    tone: "warn",
    text: "Backend no disponible; usando el snapshot local del schema (fixtures/schema.json).",
  },
}

/** Aviso sobrio de qué config se cargó (o `null` mientras aún no se resuelve la siembra). */
function seedNotice(seed: SeedState | null): string | null {
  switch (seed?.kind) {
    case "preset":
      return `Cargada la configuración estándar: ${seed.name} · dataset ${seed.datasetId}`
    case "fallback":
      return "Config vacío del schema (backend no disponible)."
    case "defaults":
      return "Config vacío del schema (empezar de cero)."
    default:
      return null
  }
}

/** Descarga `text` como archivo `filename` vía Blob + anchor (efecto DOM, no puro). */
function triggerDownload(text: string, filename: string) {
  const blob = new Blob([text], { type: "application/x-yaml" })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/** Mensaje legible de un fallo de acción YAML: detalle del backend (422) o el error crudo. */
function yamlErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return describeApiError(err.body, err.message)
  }
  return err instanceof Error ? err.message : String(err)
}

/** Indicador sobrio del estado de validación en vivo (config_hash / errores / backend). */
function HashStatus({ state }: { state: ValidationState }) {
  switch (state.kind) {
    case "valid":
      return (
        <span
          className="inline-flex items-center gap-1.5 font-mono text-xs text-eyebrow"
          title={`config_hash: ${state.hash}`}
        >
          <CircleCheck className="size-3.5" aria-hidden="true" />
          <span className="text-muted-foreground">config_hash</span>
          {state.hash.slice(0, 12)}…
        </span>
      )
    case "invalid":
      return (
        <span className="inline-flex items-center gap-1.5 text-xs text-destructive">
          <CircleAlert className="size-3.5" aria-hidden="true" />
          Config inválido · {state.count}{" "}
          {state.count === 1 ? "error" : "errores"}
        </span>
      )
    case "checking":
      return (
        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
          Validando…
        </span>
      )
    case "unreachable":
      return (
        <span className="inline-flex items-center gap-1.5 text-xs text-amber-200/80">
          <CloudOff className="size-3.5" aria-hidden="true" />
          Backend no disponible — sin validación en vivo
        </span>
      )
    default:
      return null
  }
}

/**
 * Formulario de UNA sección F1 (`section`), agrupando sus campos por `ui_group` (contrato
 * SDD-05 §5.5): si la sección declara grupos, los pinta como sub-accordions (abiertos por
 * defecto) con el título del grupo; si no (caso `data`, sub-modelos sin `ui_group`), los pinta
 * planos en una tarjeta. Los `path` de cada campo (`[section, name]`) no cambian, así que la
 * validación en vivo, el `config_hash` y el round-trip YAML siguen operando igual (B30).
 */
function ConfigSectionForm(props: {
  sectionKey: string
  schema: JsonSchema
  defs: Defs
  config: Record<string, unknown>
  setField: (path: Path, value: unknown) => void
  errors?: Map<string, string>
}) {
  const { sectionKey, schema, defs, config, setField, errors } = props
  const groups = groupedFields(schema)
  const required = new Set(schema.required ?? [])
  const renderField = ([name, fieldSchema]: [string, JsonSchema]) => (
    <FieldRenderer
      key={name}
      name={name}
      schema={fieldSchema}
      path={[sectionKey, name]}
      value={getAtPath(config, [sectionKey, name])}
      defs={defs}
      onChange={setField}
      required={required.has(name)}
      errors={errors}
    />
  )

  // Sección sin grupos declarados (p.ej. `data`: sub-modelos sin ui_group) → lista plana.
  if (groups.length <= 1) {
    const fields = groups[0]?.fields ?? []
    return (
      <div className="space-y-5 rounded-xl border border-border bg-card p-5 shadow-card">
        {fields.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Esta sección no tiene campos configurables.
          </p>
        ) : (
          fields.map(renderField)
        )}
      </div>
    )
  }

  // Varios grupos → un accordion por grupo, todos abiertos por defecto. La `value` es el índice
  // (no el título) para no depender de que los títulos sean únicos.
  return (
    <Accordion
      defaultValue={groups.map((_, index) => String(index))}
      className="rounded-xl border border-border bg-card px-4 shadow-card"
    >
      {groups.map((grp, index) => (
        <AccordionItem key={index} value={String(index)}>
          <AccordionTrigger className="font-display text-base">
            {grp.group ?? "General"}
          </AccordionTrigger>
          <AccordionContent>
            <div className="space-y-5 pt-1 pb-2">{grp.fields.map(renderField)}</div>
          </AccordionContent>
        </AccordionItem>
      ))}
    </Accordion>
  )
}

/**
 * Pestaña Config: auto-genera el formulario desde el schema que cargó el ARRANQUE de la sesión
 * (`lib/bootstrap.ts` → provider). Desde B30 muestra SOLO la sección F1 elegida en el sidebar
 * (`section`) — no las 7 apiladas — con sus campos agrupados por `ui_group` (ver
 * `ConfigSectionForm`).
 *
 * Es un EDITOR PURO (UX1): renderiza y edita, pero NO siembra el config ni arranca su vida. La
 * siembra del preset y la validación en vivo (debounce → `POST /api/validate`) viven en el
 * provider (`state/appStore.tsx`), por dos razones: (1) sin abrir esta pestaña el config también
 * está sembrado y validado, así que Ejecutar no depende de pasar por aquí; (2) esta pestaña se
 * DESMONTA al navegar a Datos/Ejecutar, y un efecto de montaje volvía a sembrar el preset,
 * pisando las ediciones del usuario y el dataset que hubiera elegido.
 *
 * La barra superior (recargar el preset, `config_hash` en vivo, round-trip YAML) es global al
 * config y persiste al navegar entre secciones. Recargar el preset o "empezar de cero" siguen
 * aquí: son acciones EXPLÍCITAS del usuario, no siembra automática. El round-trip YAML (§3.4)
 * va **vía el backend** (no se parsea YAML en el front).
 */
export function ConfigTab({ section }: { section: string }) {
  // El schema, el config, su validación, la siembra y el dataset elegido viven en el store
  // compartido (useAppState); solo las acciones YAML y sus estados son locales a esta pestaña.
  const {
    schema,
    config,
    setConfig,
    seed,
    setSeed,
    setDatasetId,
    setSelectedDataset,
    setResults,
    setLastRun,
    validation,
  } = useAppState()
  const [yamlError, setYamlError] = useState<string | null>(null)
  const [yamlBusy, setYamlBusy] = useState(false)
  const [presetBusy, setPresetBusy] = useState(false)
  const [presetError, setPresetError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // "Configuración estándar": recarga el preset estándar del backend y lo resiembra por el MISMO
  // `applyPreset` que usan RunTab/enterDemo, para que —además de sembrar config/dataset/seed— CORTE
  // la corrida previa (results/lastRun). Sin ese corte (bug P0), Resultados y Reporte seguían
  // mostrando el dominio VIEJO con lineage mixto. El endpoint estándar (`getPreset`, sin id) ignora
  // el `presetId`; RunTab está DESMONTADO en esta pestaña, así que `resetOutcome` es no-op (su
  // outcome remonta idle solo al volver a Ejecutar) — el corte esencial es el de results/lastRun.
  const handleLoadPreset = useCallback(async () => {
    setPresetError(null)
    setPresetBusy(true)
    try {
      await applyPreset("", {
        getPreset: () => getPreset(),
        setConfig,
        setDatasetId,
        setSelectedDataset,
        setSeed,
        setResults,
        setLastRun,
        resetOutcome: () => {},
      })
    } catch (err) {
      setPresetError(yamlErrorMessage(err))
    } finally {
      setPresetBusy(false)
    }
  }, [
    setConfig,
    setDatasetId,
    setSelectedDataset,
    setSeed,
    setResults,
    setLastRun,
  ])

  // "Empezar de cero": siembra el config mínimo del schema (defaults vacíos) — sin backend — y CORTA
  // la corrida previa (results/lastRun). "De cero" cambia de dominio, así que Resultados y Reporte no
  // deben seguir mostrando la corrida anterior con lineage mixto (mismo P0 que el cambio de preset).
  const handleStartBlank = useCallback(() => {
    setPresetError(null)
    setConfig(structuredClone(schema?.payload.defaults ?? {}))
    setDatasetId(null) // "de cero" no trae dataset → Ejecutar queda bloqueado hasta elegir uno
    setSeed({ kind: "defaults" })
    // Corte con la corrida previa: evita el lineage mixto en Resultados/Reporte.
    setResults(null)
    setLastRun(null)
  }, [schema, setConfig, setDatasetId, setSeed, setResults, setLastRun])

  const setField = useCallback(
    (path: Path, value: unknown) => {
      setConfig((current) => setAtPath(current, path, value))
    },
    [setConfig],
  )

  const handleDownloadYaml = async () => {
    setYamlError(null)
    setYamlBusy(true)
    try {
      const { yaml } = await configToYaml(config)
      triggerDownload(yaml, "nikodym-config.yaml")
    } catch (err) {
      setYamlError(yamlErrorMessage(err))
    } finally {
      setYamlBusy(false)
    }
  }

  const handleUploadYaml = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0]
    event.target.value = "" // permite recargar el mismo archivo
    if (!file) return
    setYamlError(null)
    setYamlBusy(true)
    try {
      const text = await file.text()
      const result = await configFromYaml(text)
      setConfig(result.config) // el backend es la fuente: puebla el form con el config migrado
    } catch (err) {
      setYamlError(yamlErrorMessage(err))
    } finally {
      setYamlBusy(false)
    }
  }

  // El schema lo carga el arranque de la sesión (provider), no esta pestaña: mientras no llega,
  // se espera. En cuanto está, el config YA viene sembrado y validado desde el store.
  if (schema === null) {
    return (
      <div className="flex items-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        Cargando configuración…
      </div>
    )
  }

  const { payload, source, error } = schema
  const properties = payload.json_schema.properties ?? {}
  const defs = payload.json_schema.$defs ?? {}
  // Solo la sección activa (elegida en el sidebar); si el schema no la trae renderable, se avisa.
  const rawSection = properties[section]
  const sectionRenderable =
    (F1_SECTIONS as readonly string[]).includes(section) &&
    isRenderableSection(rawSection)
  const resolvedSection = sectionRenderable ? resolveRef(rawSection, defs) : null
  const banner = SOURCE_BANNER[source]
  const errorLookup =
    validation.kind === "invalid" ? validation.lookup : undefined
  // El round-trip YAML necesita el backend (no se parsea YAML en el front): se deshabilita
  // sin conexión, con aviso claro (restricción del goal: el front funciona aunque caiga).
  const backendDown =
    source === "fixture-offline" || validation.kind === "unreachable"

  return (
    <TooltipProvider delay={200}>
      <div className="space-y-6">
        <div
          className={
            banner.tone === "ok"
              ? "rounded-lg border border-brand-cyan/25 bg-brand-cyan/5 px-3 py-2 text-xs text-muted-foreground"
              : "rounded-lg border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200/80"
          }
        >
          {banner.text}
          {error ? <span className="opacity-70"> ({error})</span> : null}
        </div>

        {/* Aviso sobrio de qué config se sembró (SDD §3.2): preset estándar por defecto / vacío. */}
        {seedNotice(seed) ? (
          <p
            className={
              seed?.kind === "preset"
                ? "flex items-center gap-1.5 text-xs text-eyebrow/90"
                : "text-xs text-muted-foreground"
            }
          >
            {seed?.kind === "preset" ? (
              <CircleCheck className="size-3.5" aria-hidden="true" />
            ) : null}
            {seedNotice(seed)}
          </p>
        ) : null}

        {/* Barra de estado + acciones (SDD §3.2 preset · §3.3 hash en vivo · §3.4 round-trip YAML). */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-foreground/[0.02] px-3 py-2">
          <div role="status" aria-live="polite" className="min-h-5">
            <HashStatus state={validation} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleLoadPreset}
              disabled={presetBusy || backendDown}
              title={
                backendDown
                  ? "Requiere el backend"
                  : "Recargar la configuración estándar (lista para correr)"
              }
            >
              {presetBusy ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <Sparkles aria-hidden="true" />
              )}
              Configuración estándar
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleStartBlank}
              // En la demo estática vaciar el config deja el recorrido sin salida: `handleStartBlank`
              // borra el dataset (Ejecutar queda bloqueado) y corta la corrida, pero aquí no hay
              // backend con el cual elegir otro dataset ni volver a correr. Se apaga con el motivo
              // a la vista, en vez de ofrecer un botón que rompe la demo.
              disabled={DEMO_MODE}
              title={
                DEMO_MODE
                  ? "No disponible en la demo: sirve los resultados de tres corridas ya ejecutadas, sin backend que corra un config nuevo"
                  : "Vaciar el formulario y armar el config desde cero"
              }
            >
              <FilePlus2 aria-hidden="true" />
              Empezar de cero
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleDownloadYaml}
              disabled={yamlBusy || backendDown}
              title={backendDown ? "Requiere el backend" : "Descargar el YAML canónico"}
            >
              <Download aria-hidden="true" />
              Descargar YAML
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              // En demo el YAML subido NO se lee: `demoConfigFromYaml` devuelve el config del preset
              // activo, así que el botón parecía funcionar y en realidad ignoraba el archivo del
              // usuario. Fingir que se cargó es peor que decir que no se puede.
              disabled={yamlBusy || backendDown || DEMO_MODE}
              title={
                DEMO_MODE
                  ? "No disponible en la demo: convertir un YAML propio exige el backend que valida el config"
                  : backendDown
                    ? "Requiere el backend"
                    : "Cargar un YAML existente"
              }
            >
              <Upload aria-hidden="true" />
              Cargar YAML
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".yaml,.yml"
              onChange={handleUploadYaml}
              className="hidden"
              aria-hidden="true"
            />
          </div>
        </div>
        {presetError ? (
          <p className="text-xs text-destructive">{presetError}</p>
        ) : null}
        {yamlError ? (
          <p className="text-xs text-destructive">{yamlError}</p>
        ) : backendDown ? (
          <p className="text-xs text-muted-foreground">
            Round-trip YAML deshabilitado sin backend.
          </p>
        ) : null}

        {sectionRenderable && resolvedSection ? (
          <ConfigSectionForm
            sectionKey={section}
            schema={resolvedSection}
            defs={defs}
            config={config}
            setField={setField}
            errors={errorLookup}
          />
        ) : (
          <p className="text-sm text-muted-foreground">
            La sección «{section}» no está disponible en el schema cargado.
          </p>
        )}

        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer text-muted-foreground">
            Ver config en construcción (JSON)
          </summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-lg border border-border bg-foreground/[0.02] p-3 font-mono">
            {JSON.stringify(config, null, 2)}
          </pre>
        </details>
      </div>
    </TooltipProvider>
  )
}
