import { useState } from "react"
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
import { type Path, parseJsonInput } from "@/lib/config-store"
import { errorAtPath } from "@/lib/validation"
import {
  type Defs,
  type JsonSchema,
  defaultForSchema,
  discriminatedBranches,
  discriminatorProperty,
  enumOptions,
  fieldLabel,
  multiselectOptions,
  numericBounds,
  orderedFields,
  resolveRef,
  resolveWidget,
  toggleMultiselect,
  unwrapNullable,
  variantDefaults,
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
  /** Oculta el label propio: lo pinta el contenedor (p.ej. el toggle activar/None). */
  hideLabel?: boolean
  /**
   * Lookup `pathKey→msg` de los errores del backend (SDD §3.3): cada campo pinta el
   * mensaje de su `path` si matchea. El front SOLO lo pinta; la verdad es Pydantic.
   */
  errors?: Map<string, string>
}

/** Error de validación del backend para un campo (SDD §3.3): el front SOLO lo pinta. */
function FieldError({ message }: { message: string | undefined }) {
  if (!message) return null
  return <p className="text-xs text-destructive">{message}</p>
}

/**
 * Despacha un campo del schema al widget del mapeo §5 (via `resolveWidget`) y pinta
 * label (title) + tooltip (description) + el widget. Los sub-modelos (`group`) se
 * renderizan recursivamente. B23.5a implementa `discriminated`, el toggle activar/None
 * de `X | None`, `multiselect` y el editor `json` fallback.
 */
export function FieldRenderer(props: FieldRendererProps) {
  const { schema, defs, depth = 0 } = props
  const kind = resolveWidget(schema, { defs, required: props.required })

  // Sección opcional `X | None`: se antepone el toggle activar/None (SDD §5). La unión
  // discriminada tiene su propio flujo (Select de variante) y no se trata como nullable.
  const { schema: base, nullable } = unwrapNullable(resolveRef(schema, defs))
  if (nullable && kind !== "discriminated") {
    return <NullableField {...props} baseSchema={base} depth={depth} />
  }

  if (kind === "group") {
    return <GroupField {...props} depth={depth} />
  }

  return (
    <FieldShell {...props}>
      <WidgetSwitch kind={kind} {...props} />
    </FieldShell>
  )
}

/** Label + tooltip + el widget hijo + el error del backend. Con `hideLabel`, solo el hijo. */
function FieldShell(props: FieldRendererProps & { children: React.ReactNode }) {
  const { name, schema, path, required, hideLabel, children, errors } = props
  if (hideLabel) return <>{children}</>
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
      <FieldError message={errorAtPath(errors, path)} />
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
      return <DiscriminatedField {...props} />
    case "multiselect":
      return <MultiselectField {...props} />
    default:
      return <JsonField {...props} />
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
  const { name, schema, path, value, defs, onChange, depth = 0, hideLabel, errors } =
    props
  const resolved = resolveRef(unwrapNullable(schema).schema, defs)
  const fields = orderedFields(resolved)
  const label = fieldLabel(name, schema)
  const required = new Set(resolved.required ?? [])
  const groupValue = asRecord(value)

  return (
    <fieldset
      className={cn(
        "space-y-4 rounded-lg border border-white/10 bg-white/[0.02] p-4",
        depth > 0 && "border-l-2 border-l-brand-accent/40",
      )}
    >
      {hideLabel ? null : (
        <legend className="px-1 font-display text-sm font-medium text-brand-offwhite">
          {label}
        </legend>
      )}
      {/* Error a nivel del grupo (raro; validador de modelo). Los hijos pintan el suyo. */}
      {hideLabel ? null : <FieldError message={errorAtPath(errors, path)} />}
      <GroupFieldList
        fields={fields}
        path={path}
        groupValue={groupValue}
        defs={defs}
        onChange={onChange}
        required={required}
        depth={depth}
        errors={errors}
      />
    </fieldset>
  )
}

/** Estrecha un `value` a un objeto plano (Record) o `undefined`. */
function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined
}

/**
 * Lista de campos `[name, schema]` renderizados recursivamente. Comparte el render de
 * grupo entre `GroupField` y el subform de la unión discriminada (no se duplica).
 */
function GroupFieldList(props: {
  fields: [string, JsonSchema][]
  path: Path
  groupValue: Record<string, unknown> | undefined
  defs: Defs
  onChange: (path: Path, value: unknown) => void
  required: Set<string>
  depth: number
  errors?: Map<string, string>
}) {
  const { fields, path, groupValue, defs, onChange, required, depth, errors } =
    props
  if (fields.length === 0) {
    return <p className="text-xs text-brand-placeholder">Sin campos.</p>
  }
  return (
    <>
      {fields.map(([childName, childSchema]) => (
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
          errors={errors}
        />
      ))}
    </>
  )
}

// ---------------------------------------------------------------------------
// Unión discriminada (B23.5a §5) — Select de variante + subform condicional
// ---------------------------------------------------------------------------

/**
 * Unión discriminada: `Select` del tag (`discriminator.propertyName`) + los campos de
 * SOLO la variante elegida (render recursivo compartido con `GroupField`). Al cambiar de
 * tag se reemplaza el subobjeto completo por los defaults de la nueva variante, con lo
 * que los campos de la anterior se descartan (SDD §5, ejemplo `model` logit↔xgboost).
 */
function DiscriminatedField(props: FieldRendererProps) {
  const { schema, path, value, defs, onChange, depth = 0, errors } = props
  const propName = discriminatorProperty(schema)
  const branches = discriminatedBranches(schema, defs)
  const current = asRecord(value)
  const tag = current?.[propName]
  const selectValue = typeof tag === "string" ? tag : null
  const active = branches.find((branch) => branch.tag === selectValue)

  const handleTagChange = (next: string | null) => {
    if (next === null) return
    const branch = branches.find((b) => b.tag === next)
    onChange(path, branch ? variantDefaults(branch.schema) : { [propName]: next })
  }

  const subFields = active
    ? orderedFields(active.schema).filter(([n]) => n !== propName)
    : []
  const required = new Set(active?.schema.required ?? [])

  return (
    <div className="space-y-3">
      <Select value={selectValue} onValueChange={handleTagChange}>
        <SelectTrigger id={path.join(".")} className="w-full">
          <SelectValue placeholder="Elige variante…" />
        </SelectTrigger>
        <SelectContent>
          {branches.map((branch) => (
            <SelectItem key={branch.tag} value={branch.tag}>
              {branch.tag}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {active && subFields.length > 0 ? (
        <fieldset
          className={cn(
            "space-y-4 rounded-lg border border-white/10 bg-white/[0.02] p-4",
            depth > 0 && "border-l-2 border-l-brand-accent/40",
          )}
        >
          <GroupFieldList
            fields={subFields}
            path={path}
            groupValue={current}
            defs={defs}
            onChange={onChange}
            required={required}
            depth={depth}
            errors={errors}
          />
        </fieldset>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Toggle activar/None (B23.5a §5) — sección opcional `X | None`
// ---------------------------------------------------------------------------

/**
 * Sección opcional `X | None`: `Switch` "activar" antepuesto. Desactivado ⇒ el campo vale
 * `null` (sección apagada) y no se renderiza el subform; activado ⇒ se siembra el default
 * de la variante base y se renderiza (SDD §5). Se persiste `null` (no se omite la clave)
 * para reflejar lo que emite `model_dump` de Pydantic.
 */
function NullableField(props: FieldRendererProps & { baseSchema: JsonSchema }) {
  const { name, schema, path, value, defs, onChange, baseSchema, required, errors } =
    props
  const depth = props.depth ?? 0
  const label = fieldLabel(name, schema)
  const description =
    typeof schema.description === "string" ? schema.description : undefined
  const active = value !== null && value !== undefined
  const id = path.join(".")

  const handleToggle = (next: boolean) => {
    onChange(path, next ? defaultForSchema(baseSchema, defs) : null)
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Switch
          id={id}
          checked={active}
          onCheckedChange={handleToggle}
          aria-label={`Activar ${label}`}
        />
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
        {active ? null : (
          <span className="text-xs text-brand-placeholder">(desactivado · None)</span>
        )}
      </div>
      {/* El toggle es dueño del `path`: pinta aquí su error (el hijo va con hideLabel). */}
      <FieldError message={errorAtPath(errors, path)} />
      {active ? (
        <div className="pl-1">
          <FieldRenderer
            name={name}
            schema={baseSchema}
            path={path}
            value={value}
            defs={defs}
            onChange={onChange}
            required={required}
            depth={depth}
            hideLabel
            errors={errors}
          />
        </div>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Multiselect (B23.5a §5) — grupo de checkboxes sobre el enum de los items
// ---------------------------------------------------------------------------

/**
 * `tuple[Literal, ...]` / array de enum: grupo de checkboxes con opciones = `enum` de los
 * items. El valor es el array de tags marcados en orden estable (= orden del enum, SDD §5).
 */
function MultiselectField(props: FieldRendererProps) {
  const { schema, path, value, defs, onChange } = props
  const resolved = resolveRef(unwrapNullable(schema).schema, defs)
  const options = multiselectOptions(resolved)
  const selected = new Set(Array.isArray(value) ? value : [])
  const base = path.join(".")

  return (
    <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-3">
      {options.length === 0 ? (
        <p className="text-xs text-brand-placeholder">Sin opciones.</p>
      ) : (
        options.map((option) => {
          const key = String(option)
          const optionId = `${base}.${key}`
          return (
            <label
              key={key}
              htmlFor={optionId}
              className="flex items-center gap-2 text-sm text-brand-offwhite/90"
            >
              <input
                id={optionId}
                type="checkbox"
                checked={selected.has(option)}
                onChange={(event) =>
                  onChange(
                    path,
                    toggleMultiselect(value, option, event.target.checked, options),
                  )
                }
                className="size-4 accent-brand-accent-dark"
              />
              {key}
            </label>
          )
        })
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Editor JSON fallback (B23.5a §5/§8) — tipos no mapeados / exóticos
// ---------------------------------------------------------------------------

/**
 * Editor JSON de un subárbol no mapeado (SDD §5/§8). `JSON.parse` LOCAL: si parsea,
 * propaga el valor; si no, marca el error de SINTAXIS y NO propaga (el config conserva el
 * último valor válido). La validación semántica contra el schema es del backend (B23.5b).
 * Sin Monaco/CodeMirror: un `textarea` basta y evita bundle pesado.
 */
function JsonField(props: FieldRendererProps) {
  const { path, value, onChange } = props
  const [text, setText] = useState(() =>
    value === undefined ? "" : JSON.stringify(value, null, 2),
  )
  const [error, setError] = useState<string | null>(null)

  const handleChange = (next: string) => {
    setText(next)
    const result = parseJsonInput(next)
    if (result.ok) {
      setError(null)
      onChange(path, result.value)
    } else {
      setError(result.error)
    }
  }

  return (
    <div className="space-y-1.5">
      <textarea
        id={path.join(".")}
        value={text}
        rows={5}
        spellCheck={false}
        aria-invalid={error !== null}
        onChange={(event) => handleChange(event.target.value)}
        className={cn(
          "w-full rounded-lg border bg-transparent px-2.5 py-1.5 font-mono text-xs outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30",
          error
            ? "border-destructive focus-visible:border-destructive"
            : "border-input focus-visible:border-ring",
        )}
      />
      {error ? (
        <p className="text-xs text-destructive">JSON inválido: {error}</p>
      ) : (
        <p className="text-xs text-brand-placeholder">
          Editor JSON (tipo no mapeado). Se valida en el backend al ejecutar.
        </p>
      )}
    </div>
  )
}
