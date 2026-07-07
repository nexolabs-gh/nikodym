import { useCallback, useEffect, useState } from "react"
import { Loader2 } from "lucide-react"

import { FieldRenderer } from "@/components/FieldRenderer"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { TooltipProvider } from "@/components/ui/tooltip"
import { type Path, getAtPath, setAtPath } from "@/lib/config-store"
import { fieldLabel, orderedFields, resolveRef } from "@/lib/form-engine"
import {
  F1_SECTIONS,
  type LoadedSchema,
  type SchemaSource,
  isRenderableSection,
  loadSchema,
} from "@/lib/schema"

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
    text: "El backend devolvió las secciones F1 sin expandir; usando snapshot local. Falta inlinear los sub-configs diferidos en /api/schema (nota B23.4b).",
  },
  "fixture-offline": {
    tone: "warn",
    text: "Backend no disponible; usando el snapshot local del schema (fixtures/schema.json).",
  },
}

/**
 * Pestaña Config: auto-genera el formulario desde `/api/schema` (SDD-23 §3.2) para
 * las secciones del flujo F1, cada una como un grupo (accordion). La validación
 * autoritativa es del backend (B23.5); aquí solo se edita el config como objeto JSON.
 */
export function ConfigTab() {
  const [loaded, setLoaded] = useState<LoadedSchema | null>(null)
  const [config, setConfig] = useState<Record<string, unknown>>({})

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

  const setField = useCallback((path: Path, value: unknown) => {
    setConfig((current) => setAtPath(current, path, value))
  }, [])

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
