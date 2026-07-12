import { useEffect, useState } from "react"
import {
  CircleAlert,
  Download,
  FileDown,
  FileText,
  Loader2,
  Play,
  RotateCw,
} from "lucide-react"

import { EmptyState } from "@/components/EmptyState"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { getReport, getReportPdf } from "@/lib/api"
import {
  REPORT_FILENAME,
  REPORT_PDF_FILENAME,
  reportErrorMessage,
  reportPdfErrorMessage,
} from "@/lib/report"
import { useAppState } from "@/state/appStore"

interface ReporteTabProps {
  /** Navega a otra sección del shell (la navegación vive en App, no en el store). */
  onNavigate: (section: string) => void
}

/**
 * Estado de la carga del reporte (NO es dominio): `loading` mientras se pide, `ready` con el
 * HTML crudo del backend, `error` con un mensaje legible al fallar. El caso "sin corrida"
 * (`lastRun === null`) se resuelve antes de este estado (estado vacío con CTA), no aquí.
 */
type ReportState =
  | { kind: "loading" }
  | { kind: "ready"; html: string }
  | { kind: "error"; message: string }

/**
 * Estado de la descarga del PDF (NO es dominio): `idle` en reposo, `downloading` mientras se baja
 * el binario (deshabilita el botón + spinner) y `error` con un mensaje inline al fallar. Es
 * independiente de `ReportState` porque la descarga del PDF no afecta al HTML ya embebido.
 */
type PdfDownloadState =
  | { kind: "idle" }
  | { kind: "downloading" }
  | { kind: "error"; message: string }

/**
 * Dispara la descarga del HTML como archivo con nombre fijo: crea un Blob, un object URL y un
 * `<a download>` efímero que se clickea y se limpia (revoca el URL). Aísla el efecto DOM del
 * render. El reporte es HTML standalone → se guarda tal cual, sin transformarlo.
 */
function downloadReport(html: string) {
  const blob = new Blob([html], { type: "text/html;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = REPORT_FILENAME
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/**
 * Igual que `downloadReport` pero para el PDF: recibe el `Blob` ya resuelto (el binario lo trae
 * `getReportPdf`), abre un object URL y dispara el `<a download>` efímero. Aísla el efecto DOM.
 */
function downloadPdf(blob: Blob) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = REPORT_PDF_FILENAME
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/**
 * Pestaña Reporte (B38b): muestra el informe HTML del modelo de la ÚLTIMA corrida
 * (`GET /api/report/{run_id}`) embebido en un `<iframe srcDoc>` —que lo AÍSLA de los estilos
 * de la app (el reporte trae los suyos), a diferencia de `dangerouslySetInnerHTML`— más un
 * botón para descargarlo. CERO lógica de dominio (SDD-23 §1): el HTML lo produce el motor
 * local; el front solo lo transporta, embebe y descarga. Se re-pide cuando cambia el `run_id`.
 */
export function ReporteTab({ onNavigate }: ReporteTabProps) {
  const { lastRun } = useAppState()
  const runId = lastRun?.runId ?? null
  const [state, setState] = useState<ReportState>({ kind: "loading" })
  // Se incrementa para reintentar tras un error: re-dispara el efecto sin cambiar el run_id.
  const [reloadKey, setReloadKey] = useState(0)
  // Descarga del PDF (independiente del HTML embebido): `idle` en reposo, `downloading` mientras
  // se baja el binario, `error` con un mensaje inline si falla (p.ej. 404 = la corrida no pidió PDF).
  const [pdfState, setPdfState] = useState<PdfDownloadState>({ kind: "idle" })

  // Baja el PDF de la corrida actual: pide el Blob y dispara la descarga; mapea el fallo a un
  // mensaje inline discreto sin romper la vista del HTML. No hay guarda de desmontaje: el efecto
  // es acotado (un click) y el `<a download>` no depende del ciclo de vida del componente.
  async function handleDownloadPdf() {
    if (runId === null) return
    setPdfState({ kind: "downloading" })
    try {
      const blob = await getReportPdf(runId)
      downloadPdf(blob)
      setPdfState({ kind: "idle" })
    } catch (err) {
      setPdfState({ kind: "error", message: reportPdfErrorMessage(err) })
    }
  }

  // Pide el reporte al montar y cada vez que cambie la corrida (o se reintente). Guarda de
  // vida (`alive`) para no setear estado tras desmontar o tras un run_id ya superado.
  useEffect(() => {
    if (runId === null) return
    let alive = true
    setState({ kind: "loading" })
    void (async () => {
      try {
        const html = await getReport(runId)
        if (!alive) return
        setState({ kind: "ready", html })
      } catch (err) {
        if (!alive) return
        setState({ kind: "error", message: reportErrorMessage(err) })
      }
    })()
    return () => {
      alive = false
    }
  }, [runId, reloadKey])

  // Sin corrida: estado vacío sobrio con CTA que NAVEGA a Ejecutar (mismo patrón que ResultsTab).
  if (runId === null) {
    return (
      <Card className="shadow-card">
        <EmptyState
          icon={FileText}
          title="Aún no ejecutaste un modelo"
          description="El informe HTML del modelo aparece aquí en cuanto ejecutes una corrida con la configuración estándar."
          tag="Reporte"
          action={{
            label: "Ejecutar el preset",
            onClick: () => onNavigate("ejecutar"),
            icon: Play,
          }}
        />
      </Card>
    )
  }

  if (state.kind === "loading") {
    return (
      <Card className="shadow-card">
        <CardContent
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 py-6 text-sm text-muted-foreground"
        >
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          Cargando reporte…
        </CardContent>
      </Card>
    )
  }

  if (state.kind === "error") {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-xs text-destructive">
        <p className="flex items-center gap-1.5 font-medium">
          <CircleAlert className="size-3.5" aria-hidden="true" />
          No se pudo cargar el reporte
        </p>
        <p className="mt-1 text-destructive/90">{state.message}</p>
        <div className="mt-2.5">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((k) => k + 1)}
          >
            <RotateCw aria-hidden="true" />
            Reintentar
          </Button>
        </div>
      </div>
    )
  }

  // ok: el reporte embebido (iframe aislado) + descarga. Fondo claro (el reporte lo trae).
  return (
    <Card className="shadow-card">
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1">
            <p className="font-mono text-xs uppercase tracking-[0.18em] text-eyebrow">
              Reporte del modelo
            </p>
            <p className="text-sm text-muted-foreground">
              Informe HTML de tu última corrida, aislado en su propio marco.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => downloadReport(state.html)}
            >
              <Download aria-hidden="true" />
              Descargar HTML
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleDownloadPdf}
              disabled={pdfState.kind === "downloading"}
            >
              {pdfState.kind === "downloading" ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <FileDown aria-hidden="true" />
              )}
              Descargar PDF
            </Button>
          </div>
        </div>
        {pdfState.kind === "error" && (
          <p
            role="status"
            className="flex items-center gap-1.5 text-xs text-destructive"
          >
            <CircleAlert className="size-3.5" aria-hidden="true" />
            {pdfState.message}
          </p>
        )}
        <iframe
          srcDoc={state.html}
          title="Reporte del modelo"
          className="h-[75vh] w-full rounded-lg border border-border bg-white"
        />
      </CardContent>
    </Card>
  )
}
