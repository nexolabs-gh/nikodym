import { Info } from "lucide-react"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { Path } from "@/lib/config-store"
import {
  type Defs,
  type JsonSchema,
  enumOptions,
  fieldLabel,
  numericBounds,
  orderedFields,
  resolveRef,
  resolveWidget,
  unwrapNullable,
} from "@/lib/form-engine"
import { cn } from "@/lib/utils"

export interface FieldRendererProps {
  name: string
  schema: JsonSchema
  path: Path
  value: unknown
  defs: Defs
  onChange: (path: Path, value: unknown) => void
  required?: boolean
  depth?: number
}

/**
 * Despacha un campo del schema al widget del mapeo §5 (via `resolveWidget`) y pinta
 * label (title) + tooltip (description) + el widget. Los sub-modelos (`group`) se
 * renderizan recursivamente. STUBs de B23.5: `discriminated`, `multiselect`, `json`.
 */
export function FieldRenderer(props: FieldRendererProps) {
  const { schema, defs, depth = 0 } = props
  const kind = resolveWidget(schema, { defs, required: props.required })

  if (kind === "group") {
    return <GroupField {...props} depth={depth} />
  }

  return (
    <FieldShell {...props}>
      <WidgetSwitch kind={kind} {...props} />
    </FieldShell>
  )
}

/** Label + tooltip + el widget hijo. */
function FieldShell(props: FieldRendererProps & { children: React.ReactNode }) {
  const { name, schema, path, required, children } = props
  const id = path.join(".")
  const label = fieldLabel(name, schema)
  const description =
    typeof schema.description === "string" ? schema.description : undefined
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <Label htmlFor={id} className="text-brand-offwhite/90">
          {label}
          {required ? <span className="text-brand-cyan"> *</span> : null}
        </Label>
        {description ? (
          <Tooltip>
            <TooltipTrigger
              className="text-brand-placeholder transition-colors hover:text-brand-cyan"
              aria-label={`Ayuda: ${label}`}
            >
              <Info className="size-3.5" />
            </TooltipTrigger>
            <TooltipContent>{description}</TooltipContent>
          </Tooltip>
        ) : null}
      </div>
      {children}
    </div>
  )
}

function WidgetSwitch(
  props: FieldRendererProps & { kind: ReturnType<typeof resolveWidget> },
) {
  const { kind } = props
  switch (kind) {
    case "select":
      return <SelectField {...props} />
    case "switch":
      return <SwitchField {...props} />
    case "slider":
      return <SliderField {...props} />
    case "number":
      return <NumberField {...props} />
    case "text":
      return <TextField {...props} />
    case "textarea":
      return <TextareaField {...props} />
    case "discriminated":
      return <DiscriminatedStub {...props} />
    case "multiselect":
      return <StubField {...props} note="Selección múltiple — B23.5" />
    default:
      return <StubField {...props} note="Editor JSON — B23.5" />
  }
}

// ---------------------------------------------------------------------------
// Widgets base
// ---------------------------------------------------------------------------

function currentValue(props: FieldRendererProps): unknown {
  return props.value ?? props.schema.default
}

function SelectField(props: FieldRendererProps) {
  const { schema, path, defs, onChange } = props
  const resolved = resolveRef(unwrapNullable(schema).schema, defs)
  const options = enumOptions(resolved)
  const value = currentValue(props)
  const selectValue = value === undefined || value === null ? null : String(value)
  const disabled = options.length <= 1
  return (
    <Select
      value={selectValue}
      onValueChange={(next) => onChange(path, next)}
      disabled={disabled}
    >
      <SelectTrigger id={path.join(".")} className="w-full">
        <SelectValue placeholder="—" />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={String(option)} value={String(option)}>
            {String(option)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function SwitchField(props: FieldRendererProps) {
  const { path, onChange } = props
  const checked = Boolean(currentValue(props))
  return (
    <div className="flex items-center gap-2">
      <Switch
        id={path.join(".")}
        checked={checked}
        onCheckedChange={(next) => onChange(path, next)}
      />
      <span className="text-xs text-brand-placeholder">
        {checked ? "Activado" : "Desactivado"}
      </span>
    </div>
  )
}

function SliderField(props: FieldRendererProps) {
  const { schema, path, defs, onChange } = props
  const resolved = resolveRef(unwrapNullable(schema).schema, defs)
  const { min = 0, max = 1 } = numericBounds(resolved)
  const range = max - min
  const step =
    numericBounds(resolved).step ??
    (range <= 1 ? 0.01 : range <= 10 ? 0.1 : 1)
  const raw = currentValue(props)
  const num = typeof raw === "number" ? raw : min
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs text-brand-placeholder">
        <span>{min}</span>
        <span className="font-mono text-brand-cyan">{num}</span>
        <span>{max}</span>
      </div>
      <Slider
        value={[num]}
        min={min}
        max={max}
        step={step}
        onValueChange={(next) =>
          onChange(path, Array.isArray(next) ? next[0] : next)
        }
      />
    </div>
  )
}

function NumberField(props: FieldRendererProps) {
  const { schema, path, defs, onChange } = props
  const resolved = resolveRef(unwrapNullable(schema).schema, defs)
  const { min, max, step } = numericBounds(resolved)
  const raw = currentValue(props)
  const value = typeof raw === "number" ? raw : ""
  return (
    <Input
      id={path.join(".")}
      type="number"
      value={value}
      min={min}
      max={max}
      step={step}
      onChange={(event) => {
        const text = event.target.value
        onChange(path, text === "" ? undefined : Number(text))
      }}
    />
  )
}

function TextField(props: FieldRendererProps) {
  const { schema, path, onChange } = props
  const raw = currentValue(props)
  const value = typeof raw === "string" ? raw : raw == null ? "" : String(raw)
  return (
    <Input
      id={path.join(".")}
      type="text"
      value={value}
      placeholder={
        typeof schema.description === "string" ? schema.description : undefined
      }
      onChange={(event) => onChange(path, event.target.value)}
    />
  )
}

function TextareaField(props: FieldRendererProps) {
  const { path, onChange } = props
  const raw = currentValue(props)
  const value = typeof raw === "string" ? raw : raw == null ? "" : String(raw)
  return (
    <textarea
      id={path.join(".")}
      value={value}
      rows={3}
      onChange={(event) => onChange(path, event.target.value)}
      className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
    />
  )
}

// ---------------------------------------------------------------------------
// Sub-modelos (group) — render recursivo
// ---------------------------------------------------------------------------

function GroupField(props: FieldRendererProps) {
  const { name, schema, path, value, defs, onChange, depth = 0 } = props
  const resolved = resolveRef(unwrapNullable(schema).schema, defs)
  const fields = orderedFields(resolved)
  const label = fieldLabel(name, schema)
  const required = new Set(resolved.required ?? [])
  const groupValue =
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : undefined

  return (
    <fieldset
      className={cn(
        "space-y-4 rounded-lg border border-white/10 bg-white/[0.02] p-4",
        depth > 0 && "border-l-2 border-l-brand-accent/40",
      )}
    >
      <legend className="px-1 font-display text-sm font-medium text-brand-offwhite">
        {label}
      </legend>
      {fields.length === 0 ? (
        <p className="text-xs text-brand-placeholder">Sin campos.</p>
      ) : (
        fields.map(([childName, childSchema]) => (
          <FieldRenderer
            key={childName}
            name={childName}
            schema={childSchema}
            path={[...path, childName]}
            value={groupValue?.[childName]}
            defs={defs}
            onChange={onChange}
            required={required.has(childName)}
            depth={depth + 1}
          />
        ))
      )}
    </fieldset>
  )
}

// ---------------------------------------------------------------------------
// STUBs (B23.5): unión discriminada, multiselect, json
// ---------------------------------------------------------------------------

function DiscriminatedStub(props: FieldRendererProps) {
  const { schema, path, onChange } = props
  const discProp = schema.discriminator?.propertyName ?? "type"
  const branches = schema.oneOf ?? schema.anyOf ?? []
  const mapping = schema.discriminator?.mapping
  const options = mapping
    ? Object.keys(mapping)
    : branches
        .map((branch) => branch.properties?.[discProp]?.const)
        .filter((tag): tag is string => typeof tag === "string")
  const raw = props.value
  const current =
    raw && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)[discProp]
      : undefined
  const selectValue =
    current === undefined || current === null ? null : String(current)
  return (
    <div className="space-y-2">
      <Select
        value={selectValue}
        onValueChange={(next) => onChange([...path, discProp], next)}
      >
        <SelectTrigger className="w-full">
          <SelectValue placeholder="Elige variante…" />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-xs text-brand-placeholder">
        Subform condicional de la variante — B23.5.
      </p>
    </div>
  )
}

function StubField(props: FieldRendererProps & { note: string }) {
  const value = currentValue(props)
  return (
    <div className="space-y-1.5">
      <pre className="max-h-32 overflow-auto rounded-lg border border-white/10 bg-white/[0.02] p-2.5 font-mono text-xs text-brand-placeholder">
        {value === undefined ? "—" : JSON.stringify(value, null, 2)}
      </pre>
      <p className="text-xs text-brand-placeholder">{props.note}</p>
    </div>
  )
}
