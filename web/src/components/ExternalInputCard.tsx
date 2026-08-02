import { useRef, useState, type ChangeEvent } from "react"
import { CircleAlert, FileUp, Loader2, TriangleAlert } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { ApiError, uploadDataset, type ConfigDict } from "@/lib/api"
import { ALLOWED_DATA_EXTENSIONS, isAllowedDataFile } from "@/lib/datasets"
import {
  CARTERA_KEY_PATH,
  artifactKey,
  carteraKeyColumn,
  carteraKeyMismatch,
  withColumnMapping,
  type ExternalInput,
} from "@/lib/external-artifacts"
import type { ExternalArtifact } from "@/lib/jobs"
import { describeApiError } from "@/lib/validation"

/** Valor del `<Select>` que representa «sin llave»: alinear por orden de filas (D-PUE-6). */
const POR_ORDEN = "__por_orden__"

/**
 * Etiqueta de la opción «sin llave».
 *
 * ⚠️ Vive en una constante porque hay que escribirla DOS veces: en el `<SelectItem>` y en el render
 * del valor elegido. `Select.Value` pinta el **valor** crudo, no el texto del item —es la misma
 * trampa que este repo ya documentó con `String(option)`—, así que sin el render explícito el
 * usuario leía `__por_orden__` en el control. Se vio abriendo la pantalla, no en un test.
 */
const ETIQUETA_POR_ORDEN = "No tengo esa columna: usa el mismo orden de filas"

interface ExternalInputCardProps {
  artifact: ExternalArtifact
  input: ExternalInput | undefined
  config: ConfigDict
  /** Columnas de la cartera; `undefined` mientras no haya ninguna elegida. */
  carteraColumns?: string[]
  onInput: (key: string, input: ExternalInput | undefined) => void
  onConfig: (next: ConfigDict) => void
}

/**
 * Pide un resultado ya calculado y deja que el usuario lo mapee **por clicks** (D-PUE-5).
 *
 * Tres cosas que este componente hace a propósito:
 *
 * 1. **Nunca enseña la clave del artefacto.** Lo que se lee es el nombre de negocio que declara el
 *    catálogo; `(dominio, clave)` es coordenada interna, igual que el `path` de una decisión
 *    obligatoria.
 * 2. **Los selectores se pueblan con las columnas REALES del archivo subido.** Teclear un nombre y
 *    descubrir el error al correr es justo lo que la interfaz existe para evitar.
 * 3. **El mapeo se escribe en el config**, en los campos que ya existen y que edita quien trabaja
 *    por código. No hay canal paralelo, así que el `config_hash` es el mismo por los dos caminos.
 */
export function ExternalInputCard({
  artifact,
  input,
  config,
  carteraColumns,
  onInput,
  onConfig,
}: ExternalInputCardProps) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const key = artifactKey(artifact.artifact)

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = "" // permite volver a subir el mismo archivo
    if (!file) return
    setError(null)
    if (!isAllowedDataFile(file.name)) {
      setError(`Formato no soportado: usa ${ALLOWED_DATA_EXTENSIONS.join(", ")}.`)
      return
    }
    setUploading(true)
    try {
      const resp = await uploadDataset(file)
      onInput(key, {
        datasetId: resp.dataset_id,
        fileName: file.name,
        columns: resp.columns.map((c) => c.name),
        keyColumn: null,
      })
    } catch (err) {
      setError(mensajeDeError(err))
    } finally {
      setUploading(false)
    }
  }

  const columnas = input?.columns ?? []
  const porOrden = input !== undefined && input.keyColumn === null
  const llaveDesalineada = input !== undefined && carteraKeyMismatch(config, input.keyColumn)
  const llaveDeLaCartera = carteraKeyColumn(config)

  /**
   * Elegir la llave del archivo declara **también** la de la cartera (D-PUE-6-bis, §8.3).
   *
   * 🔴 Sin esto, el modo «con llave» no alinea por etiqueta: cruza. Se indexaría un solo lado, y la
   * cartera conservaría su índice posicional. Escribirlo aquí hace que el caso correcto sea el que
   * ocurre sin pedir nada; si la cartera no trae esa columna, no se inventa un valor y el aviso de
   * abajo ofrece las dos salidas honestas.
   */
  function elegirLlave(value: string) {
    const keyColumn = value === POR_ORDEN ? null : value
    if (input !== undefined) onInput(key, { ...input, keyColumn })
    if (keyColumn !== null && (carteraColumns ?? []).includes(keyColumn)) {
      onConfig(withColumnMapping(config, [CARTERA_KEY_PATH], keyColumn))
    }
  }

  return (
    <Card className="shadow-card">
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <p className="font-mono text-xs uppercase tracking-[0.18em] text-eyebrow">
            Lo que traes de tu modelo
          </p>
          <p className="text-sm font-medium text-foreground">{artifact.label}</p>
          <p className="text-sm text-muted-foreground">
            Sube una tabla con una fila por operación. Después eliges qué columna es cada cosa.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept={ALLOWED_DATA_EXTENSIONS.join(",")}
            onChange={handleUpload}
            className="hidden"
            aria-hidden="true"
            tabIndex={-1}
          />
          <Button
            type="button"
            variant="outline"
            disabled={uploading}
            onClick={() => fileRef.current?.click()}
            data-testid={`subir-insumo-${key}`}
          >
            {uploading ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <FileUp className="size-3.5" aria-hidden="true" />
            )}
            {input === undefined ? "Subir archivo" : "Cambiar archivo"}
          </Button>
          {input !== undefined ? (
            <span className="text-xs text-muted-foreground">
              {input.fileName} · {input.columns.length} columnas
            </span>
          ) : null}
        </div>

        {error !== null ? (
          <p className="inline-flex items-center gap-1.5 text-xs text-amber-200/90">
            <CircleAlert className="size-3.5" aria-hidden="true" />
            {error}
          </p>
        ) : null}

        {input !== undefined ? (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor={`llave-${key}`}>{artifact.key_question}</Label>
              <Select
                value={input.keyColumn ?? POR_ORDEN}
                onValueChange={(value) => {
                  if (typeof value !== "string" || value === "") return
                  elegirLlave(value)
                }}
              >
                <SelectTrigger id={`llave-${key}`} className="w-full">
                  <SelectValue>
                    {(value) => (value === POR_ORDEN ? ETIQUETA_POR_ORDEN : String(value))}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={POR_ORDEN}>{ETIQUETA_POR_ORDEN}</SelectItem>
                  {columnas.map((columna) => (
                    <SelectItem key={columna} value={columna}>
                      {columna}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {llaveDesalineada ? (
              /* D-PUE-6-bis: la cartera no se identifica con esa columna, así que emparejar por
                 etiqueta cruzaría las filas. El backend lo rechaza; aquí se dice antes y con las
                 DOS salidas, porque quien está probando algo rápido tiene que poder seguir. */
              <p
                data-testid={`aviso-llave-cartera-${key}`}
                className="flex items-start gap-1.5 rounded-lg border border-amber-400/30 bg-amber-400/5 p-2.5 text-xs leading-relaxed text-amber-200/90"
              >
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                <span>
                  Tu cartera{" "}
                  {llaveDeLaCartera === null
                    ? "no declara ninguna columna que identifique cada operación"
                    : `identifica sus operaciones con «${llaveDeLaCartera}»`}
                  , así que no se pueden emparejar por «{input.keyColumn}». Elige esa misma columna
                  como identificador en tu cartera, o vuelve aquí y usa el orden de filas.
                </span>
              </p>
            ) : null}

            {porOrden ? (
              /* D-PUE-6: el aviso es obligatorio, no cosmético. Si las filas están en otro orden y
                 el conteo coincide, la corrida termina sin un solo error con la probabilidad de
                 cada cliente asignada a otro. Nadie puede detectarlo después. */
              <p
                data-testid={`aviso-por-orden-${key}`}
                className="flex items-start gap-1.5 rounded-lg border border-amber-400/30 bg-amber-400/5 p-2.5 text-xs leading-relaxed text-amber-200/90"
              >
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                <span>
                  Sin una columna que identifique cada operación, la fila 1 de este archivo se
                  empareja con la fila 1 de tu cartera, la 2 con la 2, y así. Si el archivo está
                  ordenado de otra forma, el resultado sale igual y es incorrecto. Queda anotado en
                  el informe.
                </span>
              </p>
            ) : null}

            {artifact.columns.map((rol) => {
              const actual = rol.config_paths
                .map((path) => valueAtPath(config, path))
                .find((value): value is string => typeof value === "string")
              const id = `rol-${key}-${rol.config_paths[0]}`
              return (
                <div key={rol.config_paths[0]} className="space-y-1.5">
                  <Label htmlFor={id}>{rol.question}</Label>
                  <Select
                    value={actual !== undefined && columnas.includes(actual) ? actual : ""}
                    onValueChange={(value) => {
                      if (typeof value !== "string" || value === "") return
                      onConfig(withColumnMapping(config, rol.config_paths, value))
                    }}
                  >
                    <SelectTrigger id={id} className="w-full">
                      <SelectValue placeholder="Elige una columna" />
                    </SelectTrigger>
                    <SelectContent>
                      {columnas.map((columna) => (
                        <SelectItem key={columna} value={columna}>
                          {columna}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )
            })}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

/** Mensaje legible de un fallo de la API, igual que en la subida del dataset. */
function mensajeDeError(err: unknown): string {
  if (err instanceof ApiError) return describeApiError(err.body, err.message)
  return err instanceof Error ? err.message : String(err)
}

/** Valor del config en un path con puntos; `undefined` si la clave no existe. */
function valueAtPath(config: ConfigDict, path: string): unknown {
  let node: unknown = config
  for (const segment of path.split(".")) {
    if (typeof node !== "object" || node === null) return undefined
    node = (node as Record<string, unknown>)[segment]
  }
  return node
}
