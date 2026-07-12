import { useEffect, useRef, useState, type ChangeEvent } from "react"
import { ArrowRight, CircleAlert, Loader2, Play, Upload, X } from "lucide-react"

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
import {
  ApiError,
  listDatasets,
  uploadDataset,
  type DatasetInfo,
} from "@/lib/api"
import {
  ALLOWED_DATA_EXTENSIONS,
  datasetOptionLabel,
  fromCatalog,
  fromUpload,
  isAllowedDataFile,
  type SelectedDataset,
} from "@/lib/datasets"
import { describeApiError } from "@/lib/validation"
import { useAppState } from "@/state/appStore"

interface DatosTabProps {
  /** Navega a otra sección del shell (la navegación vive en App, no en el store). */
  onNavigate: (section: string) => void
}

/** Mensaje legible de un fallo de la API (subida): detalle del backend o el error crudo. */
function uploadErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return describeApiError(err.body, err.message)
  }
  return err instanceof Error ? err.message : String(err)
}

/**
 * Pestaña Datos (B36c): elige el dataset de la corrida por una de dos rutas —un dataset de
 * ejemplo del catálogo (GET /api/datasets) o SUBIR el propio (POST /api/upload, CSV/Excel/
 * Parquet)—. Cualquiera de las dos setea `datasetId` (habilita Ejecutar) y `selectedDataset`
 * (el preview). CERO lógica de dominio (SDD-23 §1): el front normaliza formas y transporta;
 * el backend lee el archivo y expone columnas. Si el backend está caído, degrada suave.
 */
export function DatosTab({ onNavigate }: DatosTabProps) {
  const {
    datasetId,
    setDatasetId,
    selectedDataset,
    setSelectedDataset,
    welcomeDismissed,
    setWelcomeDismissed,
  } = useAppState()

  const [datasets, setDatasets] = useState<DatasetInfo[]>([])
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // Al montar: trae el catálogo sintético. Si el backend está caído, degrada suave (aviso
  // "requiere el backend") sin romper la pestaña; la subida también quedará indisponible.
  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const list = await listDatasets()
        if (!alive) return
        setDatasets(list)
        setCatalogError(null)
      } catch {
        if (!alive) return
        setCatalogError(
          "No se pudo cargar el catálogo de datasets (requiere el backend).",
        )
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  // El arranque siembra el `datasetId` recomendado por el preset, pero no su ficha (el catálogo
  // se pide aquí). En cuanto llega, se completa el preview de ese dataset. SOLO rellena el hueco
  // (`selectedDataset === null`): nunca pisa una elección ni una subida del usuario.
  useEffect(() => {
    if (selectedDataset !== null || datasetId === null) return
    const info = datasets.find((d) => d.id === datasetId)
    if (info) setSelectedDataset(fromCatalog(info))
  }, [datasets, datasetId, selectedDataset, setSelectedDataset])

  // El <Select> refleja el datasetId SOLO si es una opción del catálogo; un id subido (fuera
  // del catálogo) deja el selector en su placeholder, sin mostrar un id ajeno a la lista.
  const catalogValue = datasets.some((d) => d.id === datasetId)
    ? datasetId
    : null

  function handlePickCatalog(id: string | null) {
    if (id === null) return
    const info = datasets.find((d) => d.id === id)
    if (!info) return
    setSelectedDataset(fromCatalog(info))
    setDatasetId(info.id)
  }

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = "" // permite re-subir el mismo archivo
    if (!file) return
    setUploadError(null)
    if (!isAllowedDataFile(file.name)) {
      setUploadError(
        `Formato no soportado: usa ${ALLOWED_DATA_EXTENSIONS.join(", ")}.`,
      )
      return
    }
    setUploading(true)
    try {
      const resp = await uploadDataset(file)
      setSelectedDataset(fromUpload(resp))
      setDatasetId(resp.dataset_id)
    } catch (err) {
      setUploadError(uploadErrorMessage(err))
    } finally {
      setUploading(false)
    }
  }

  const catalogItems = datasets.map((d) => ({
    label: datasetOptionLabel(d),
    value: d.id,
  }))

  return (
    <div className="space-y-6">
      {/* Get-started del primer paso: qué es el flujo y que se puede correr sin configurar nada. */}
      {welcomeDismissed ? null : (
        <WelcomeCard
          onRun={() => onNavigate("ejecutar")}
          onDismiss={() => setWelcomeDismissed(true)}
        />
      )}

      {/* Sección A — Datasets de ejemplo (catálogo sintético). */}
      <Card className="shadow-card">
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <p className="font-mono text-xs uppercase tracking-[0.18em] text-eyebrow">
              Datasets de ejemplo
            </p>
            <p className="text-sm text-muted-foreground">
              Elige uno de los datasets sintéticos deterministas para correr el
              pipeline sin traer datos propios.
            </p>
          </div>

          {catalogError ? (
            <p className="inline-flex items-center gap-1.5 text-xs text-amber-200/90">
              <CircleAlert className="size-3.5" aria-hidden="true" />
              {catalogError}
            </p>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="dataset-catalogo">Dataset de ejemplo</Label>
              <Select
                items={catalogItems}
                value={catalogValue}
                onValueChange={handlePickCatalog}
                disabled={datasets.length === 0}
              >
                <SelectTrigger
                  id="dataset-catalogo"
                  className="w-full"
                  aria-label="Elegir dataset de ejemplo"
                >
                  <SelectValue placeholder="Elige un dataset de ejemplo…" />
                </SelectTrigger>
                <SelectContent>
                  {datasets.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {datasetOptionLabel(d)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Sección B — Tu dataset (subida propia). */}
      <Card className="shadow-card">
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <p className="font-mono text-xs uppercase tracking-[0.18em] text-eyebrow">
              Tu dataset
            </p>
            <p className="text-sm text-muted-foreground">
              Sube tu propio panel en CSV, Excel (.xlsx) o Parquet. El backend lo
              lee y expone sus columnas; el front no calcula dominio.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              {uploading ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <Upload aria-hidden="true" />
              )}
              Subir archivo (CSV, Excel, Parquet)
            </Button>
            {uploading ? (
              <span className="text-xs text-muted-foreground">Subiendo…</span>
            ) : null}
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.xlsx,.parquet"
              onChange={handleUpload}
              className="hidden"
              aria-hidden="true"
            />
          </div>

          {uploadError ? (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-xs text-destructive">
              <p className="flex items-center gap-1.5 font-medium">
                <CircleAlert className="size-3.5" aria-hidden="true" />
                No se pudo subir el archivo
              </p>
              <p className="mt-1 text-destructive/90">{uploadError}</p>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* Preview del dataset activo (persistido en el store). */}
      {selectedDataset ? (
        <DatasetPreview
          dataset={selectedDataset}
          onContinue={() => onNavigate("ejecutar")}
        />
      ) : null}
    </div>
  )
}

interface WelcomeCardProps {
  onRun: () => void
  onDismiss: () => void
}

/**
 * Tarjeta de bienvenida del primer paso (get-started, UX1): explica el scoring de punta a punta
 * en cuatro líneas y deja explícito que el preset ya viene cargado y validado, así que se puede
 * ejecutar sin configurar nada. Descartable (se cierra por sesión, vía el store). Tono de marca:
 * sobrio, sin marketing. No calcula ni decide nada: es texto + dos CTA.
 */
function WelcomeCard({ onRun, onDismiss }: WelcomeCardProps) {
  return (
    <Card className="shadow-card">
      <CardContent className="space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1.5">
            <p className="font-mono text-xs uppercase tracking-[0.18em] text-eyebrow">
              Cómo funciona
            </p>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              El pipeline va del dataset al scorecard en un paso: binning, selección de
              variables, modelo, escalado a puntaje y calibración de PD. Eliges un dataset,
              ejecutas la corrida y revisas los resultados y el reporte. La configuración
              estándar ya viene cargada y validada, así que puedes ejecutar el preset tal cual,
              sin configurar nada. Ajustar la configuración es opcional.
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onDismiss}
            aria-label="Cerrar la introducción"
            title="Cerrar"
          >
            <X aria-hidden="true" />
          </Button>
        </div>
        <Button onClick={onRun}>
          <Play aria-hidden="true" />
          Ejecutar el preset
          <ArrowRight aria-hidden="true" />
        </Button>
      </CardContent>
    </Card>
  )
}

interface DatasetPreviewProps {
  dataset: SelectedDataset
  onContinue: () => void
}

/**
 * Preview del dataset activo: nombre + tamaño y una tabla de columnas (name, dtype, y `role`
 * solo si alguna columna lo trae — el catálogo sí, una subida no). Patrón de tabla de
 * ResultsTab. Solo presenta lo ya normalizado por `fromCatalog`/`fromUpload`.
 */
function DatasetPreview({ dataset, onContinue }: DatasetPreviewProps) {
  const hasRole = dataset.columns.some((c) => c.role)
  return (
    <Card className="shadow-card">
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.18em] text-eyebrow">
              Dataset activo
            </p>
            <p className="mt-1 text-sm font-medium text-foreground">
              {dataset.name}
            </p>
          </div>
          <p className="font-mono text-xs text-muted-foreground">
            {dataset.nRows.toLocaleString("es-CL")} filas ·{" "}
            {dataset.columns.length} columnas
          </p>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[0.68rem] uppercase tracking-wide text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Columna</th>
                <th className="py-2 pr-3 font-medium">Tipo</th>
                {hasRole ? (
                  <th className="py-2 pr-3 font-medium">Rol</th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {dataset.columns.map((c) => (
                <tr key={c.name} className="border-b border-border">
                  <td className="py-2 pr-3 text-foreground">{c.name}</td>
                  <td className="py-2 pr-3 font-mono text-muted-foreground">
                    {c.dtype}
                  </td>
                  {hasRole ? (
                    <td className="py-2 pr-3 text-muted-foreground">
                      {c.role ?? "—"}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <Button onClick={onContinue}>
            Continuar a Ejecutar
            <ArrowRight aria-hidden="true" />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
