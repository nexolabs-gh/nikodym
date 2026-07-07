import { useCallback, useEffect, useRef, useState } from "react"
import {
  CircleAlert,
  CircleCheck,
  CloudOff,
  Download,
  Loader2,
  Upload,
} from "lucide-react"

import { FieldRenderer } from "@/components/FieldRenderer"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { Button } from "@/components/ui/button"
import { TooltipProvider } from "@/components/ui/tooltip"
import {
  ApiError,
  configFromYaml,
  configToYaml,
  validateConfig,
} from "@/lib/api"
import { type Path, getAtPath, setAtPath } from "@/lib/config-store"
import { fieldLabel, orderedFields, resolveRef } from "@/lib/form-engine"
import {
  F1_SECTIONS,
  type LoadedSchema,
  type SchemaSource,
  isRenderableSection,
  loadSchema,
} from "@/lib/schema"
import { buildErrorLookup, describeApiError } from "@/lib/validation"

const SOURCE_BANNER: Record<
  SchemaSource,
  { tone: "ok" | "warn"; text: string }
> = {
  backend: {
    tone: "ok",
    text: "Schema en vivo desde el backend (/api/schema).",
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

/**
 * Estado de la validación en vivo (SDD-23 §3.3/§7): la verdad la produce el backend
 * (`POST /api/validate`); el front solo transporta el `config_hash` o los errores.
 */
type ValidationState =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "valid"; hash: string }
  | { kind: "invalid"; count: number; lookup: Map<string, string> }
  | { kind: "unreachable" }

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
          className="inline-flex items-center gap-1.5 font-mono text-xs text-brand-cyan"
          title={`config_hash: ${state.hash}`}
        >
          <CircleCheck className="size-3.5" aria-hidden="true" />
          <span className="text-brand-gray">config_hash</span>
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
        <span className="inline-flex items-center gap-1.5 text-xs text-brand-placeholder">
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
 * Pestaña Config: auto-genera el formulario desde `/api/schema` (SDD-23 §3.2) para las
 * secciones del flujo F1, cada una como un grupo (accordion), y valida EN VIVO por
 * reconstrucción en el backend (SDD-23 §3.3/§7, B23.5b): en cada edición hace `POST
 * /api/validate` (debounced) y pinta el `config_hash` en vivo o los errores inline por campo.
 * El round-trip YAML (§3.4) descarga/carga el config **vía el backend** (no se parsea YAML aquí).
 */
export function ConfigTab() {
  const [loaded, setLoaded] = useState<LoadedSchema | null>(null)
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [validation, setValidation] = useState<ValidationState>({ kind: "idle" })
  const [yamlError, setYamlError] = useState<string | null>(null)
  const [yamlBusy, setYamlBusy] = useState(false)
  const requestSeq = useRef(0)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    let alive = true
    void loadSchema().then((result) => {
      if (!alive) return
      setLoaded(result)
      setConfig(structuredClone(result.payload.defaults))
    })
    return () => {
      alive = false
    }
  }, [])

  // Validación en vivo: en cada cambio del config re-valida en el backend con debounce
  // (~350ms). El timer previo se cancela en el cleanup; el contador `requestSeq` descarta
  // respuestas obsoletas (última petición gana). No congela la edición (SDD §3.3, restricción).
  useEffect(() => {
    if (!loaded) return
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
    }, 350)
    return () => clearTimeout(timer)
  }, [config, loaded])

  const setField = useCallback((path: Path, value: unknown) => {
    setConfig((current) => setAtPath(current, path, value))
  }, [])

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

  if (!loaded) {
    return (
      <div className="flex items-center gap-2 py-16 text-sm text-brand-placeholder">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        Cargando schema…
      </div>
    )
  }

  const { payload, source, error } = loaded
  const properties = payload.json_schema.properties ?? {}
  const defs = payload.json_schema.$defs ?? {}
  const sections = payload.section_order.filter(
    (section) =>
      (F1_SECTIONS as readonly string[]).includes(section) &&
      isRenderableSection(properties[section]),
  )
  const omitted = payload.section_order.filter(
    (section) => !(F1_SECTIONS as readonly string[]).includes(section),
  )
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
              ? "rounded-lg border border-brand-cyan/25 bg-brand-cyan/5 px-3 py-2 text-xs text-brand-placeholder"
              : "rounded-lg border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200/80"
          }
        >
          {banner.text}
          {error ? <span className="opacity-70"> ({error})</span> : null}
        </div>

        {/* Barra de estado + acciones (SDD §3.3 hash en vivo · §3.4 round-trip YAML). */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2">
          <div role="status" aria-live="polite" className="min-h-5">
            <HashStatus state={validation} />
          </div>
          <div className="flex items-center gap-2">
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
              disabled={yamlBusy || backendDown}
              title={backendDown ? "Requiere el backend" : "Cargar un YAML existente"}
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
        {yamlError ? (
          <p className="text-xs text-destructive">{yamlError}</p>
        ) : backendDown ? (
          <p className="text-xs text-brand-placeholder">
            Round-trip YAML deshabilitado sin backend.
          </p>
        ) : null}

        {sections.length === 0 ? (
          <p className="text-sm text-brand-placeholder">
            El schema no trae secciones F1 renderables.
          </p>
        ) : (
          <Accordion defaultValue={[sections[0]]} className="rounded-xl border border-white/10 bg-card px-4 shadow-card">
            {sections.map((section) => {
              const resolved = resolveRef(properties[section], defs)
              const fields = orderedFields(resolved)
              const required = new Set(resolved.required ?? [])
              return (
                <AccordionItem key={section} value={section}>
                  <AccordionTrigger className="font-display text-base">
                    {fieldLabel(section, resolved)}
                  </AccordionTrigger>
                  <AccordionContent>
                    <div className="space-y-5 pt-1 pb-2">
                      {fields.map(([name, schema]) => (
                        <FieldRenderer
                          key={name}
                          name={name}
                          schema={schema}
                          path={[section, name]}
                          value={getAtPath(config, [section, name])}
                          defs={defs}
                          onChange={setField}
                          required={required.has(name)}
                          errors={errorLookup}
                        />
                      ))}
                    </div>
                  </AccordionContent>
                </AccordionItem>
              )
            })}
          </Accordion>
        )}

        <p className="text-xs leading-relaxed text-brand-placeholder">
          <span className="text-brand-gray">Secciones no-F1 omitidas en B23.4b:</span>{" "}
          {omitted.join(", ") || "—"}. Se expondrán por flujo elegido en B23.5+.
        </p>

        <details className="text-xs text-brand-placeholder">
          <summary className="cursor-pointer text-brand-gray">
            Ver config en construcción (JSON)
          </summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-lg border border-white/10 bg-white/[0.02] p-3 font-mono">
            {JSON.stringify(config, null, 2)}
          </pre>
        </details>
      </div>
    </TooltipProvider>
  )
}
