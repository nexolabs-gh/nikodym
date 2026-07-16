import { useEffect, useState } from "react"
import {
  ChartColumn,
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
import {
  ApiError,
  getReport,
  getReportDocx,
  getReportEditable,
  getReportPdf,
} from "@/lib/api"
import {
  REPORT_DOCX_FILENAME,
  REPORT_EDITABLE_FILENAME,
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
  // El preset corrido no genera informe (404 del backend, p. ej. IFRS 9 / ECL): NO es un fallo
  // de carga, es un estado esperado → estado vacío sobrio, no el card de error rojo.
  | { kind: "no-report" }
  | { kind: "error"; message: string }

/**
 * Los entregables descargables además del HTML embebido. Cada uno es opt-in vía `report.formats`:
 * el preset estándar pide los cuatro, pero una corrida configurada a mano puede no traerlos (→ 404,
 * que se mapea a un mensaje inline, no a un error de la vista).
 */
type Entregable = "pdf" | "editable" | "docx"

/**
 * Estado de una descarga binaria (NO es dominio): `idle` en reposo, `downloading` mientras se baja
 * (deshabilita el botón + spinner) y `error` con un mensaje inline al fallar. `which` recuerda QUÉ
 * entregable está en curso para no bloquear los tres botones a la vez. Es independiente de
 * `ReportState` porque estas descargas no afectan al HTML ya embebido.
 */
type DownloadState =
  | { kind: "idle" }
  | { kind: "downloading"; which: Entregable }
  | { kind: "error"; message: string }

/** Qué pedir, cómo llamar al archivo y qué botón mostrar, por entregable. */
const ENTREGABLES: Record<
  Entregable,
  { fetch: (runId: string) => Promise<Blob>; filename: string; label: string }
> = {
  pdf: { fetch: getReportPdf, filename: REPORT_PDF_FILENAME, label: "Descargar PDF" },
  editable: {
    fetch: getReportEditable,
    filename: REPORT_EDITABLE_FILENAME,
    label: "Base editable (Quarto)",
  },
  docx: { fetch: getReportDocx, filename: REPORT_DOCX_FILENAME, label: "Word (.docx)" },
}

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
 * Igual que `downloadReport` pero para los binarios (PDF, Word, ZIP de la base editable): recibe el
 * `Blob` ya resuelto, abre un object URL y dispara el `<a download>` efímero. Aísla el efecto DOM.
 */
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/**
 * Pestaña Reporte: muestra el informe de validación de la ÚLTIMA corrida
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
  // Descarga de los entregables binarios (independiente del HTML embebido): `idle` en reposo,
  // `downloading` mientras se baja, `error` con un mensaje inline si falla (p.ej. 404 = la corrida
  // no pidió ese formato, o el servidor no tiene el extra instalado).
  const [download, setDownload] = useState<DownloadState>({ kind: "idle" })

  // Baja un entregable de la corrida actual: pide el Blob y dispara la descarga; mapea el fallo a un
  // mensaje inline discreto sin romper la vista del HTML. No hay guarda de desmontaje: el efecto
  // es acotado (un click) y el `<a download>` no depende del ciclo de vida del componente.
  async function handleDownload(which: Entregable) {
    if (runId === null) return
    const entregable = ENTREGABLES[which]
    setDownload({ kind: "downloading", which })
    try {
      const blob = await entregable.fetch(runId)
      downloadBlob(blob, entregable.filename)
      setDownload({ kind: "idle" })
    } catch (err) {
      setDownload({ kind: "error", message: reportPdfErrorMessage(err) })
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
        // Un 404 significa que la corrida existe pero el preset no genera informe (p. ej. IFRS 9):
        // estado esperado, no un fallo → estado vacío, no el card rojo.
        if (err instanceof ApiError && err.status === 404) {
          setState({ kind: "no-report" })
        } else {
          setState({ kind: "error", message: reportErrorMessage(err) })
        }
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
          description="El informe de validación del modelo aparece aquí en cuanto ejecutes una corrida con la configuración estándar."
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

  // El preset corrido no genera informe (p. ej. IFRS 9 / ECL): estado vacío sobrio que remite a
  // Resultados, NO el card de error rojo (que leería como una falla en medio de una demo).
  if (state.kind === "no-report") {
    return (
      <Card className="shadow-card">
        <EmptyState
          icon={FileText}
          title="Este preset no genera un informe"
          description="El informe de validación (HTML, PDF, Word y base editable) acompaña al preset del scorecard. Otros presets —como IFRS 9 / ECL— entregan todo su resultado en la pestaña Resultados y no producen un documento de validación."
          tag="Reporte"
          action={{
            label: "Ver resultados",
            onClick: () => onNavigate("resultados"),
            icon: ChartColumn,
          }}
        />
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
              Informe de tu última corrida. Descárgalo cerrado (HTML o PDF), o llévate la base
              editable y escribe tu documentación encima.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => downloadReport(state.html)}
            >
              <Download aria-hidden="true" />
              Descargar HTML
            </Button>
            {(["pdf", "docx", "editable"] as const).map((which) => (
              <Button
                key={which}
                variant="outline"
                size="sm"
                onClick={() => void handleDownload(which)}
                disabled={download.kind === "downloading"}
              >
                {download.kind === "downloading" && download.which === which ? (
                  <Loader2 className="animate-spin" aria-hidden="true" />
                ) : (
                  <FileDown aria-hidden="true" />
                )}
                {ENTREGABLES[which].label}
              </Button>
            ))}
          </div>
        </div>
        {download.kind === "error" && (
          <p
            role="status"
            className="flex items-center gap-1.5 text-xs text-destructive"
          >
            <CircleAlert className="size-3.5" aria-hidden="true" />
            {download.message}
          </p>
        )}
        <iframe
          srcDoc={state.html}
          title="Reporte del modelo"
          className="h-[75vh] w-full rounded-lg border border-border bg-white"
        />
        {/* Bajo el iframe, no en la fila de descargas: un botón "Proponer un caso" junto a
            "Descargar PDF" convertiría el entregable en un embudo. Sin gate DEMO_MODE — en local
            el lector acaba de generar su informe y la frase sigue siendo cierta.
            `text-eyebrow` (no `text-brand-accent-dark`): este último es un token FIJO y falla AA
            en ambos temas; eyebrow es theme-aware (8.2:1 en claro y oscuro). Subrayado en reposo:
            sin él, el único enlace de conversión de la pestaña queda menos visible que el gris. */}
        <p className="text-xs leading-relaxed text-muted-foreground">
          Este informe lo escribe el motor. Defenderlo ante Validación —el corte que elegiste, el
          ancla de calibración, los supuestos— no.{" "}
          <a
            href="https://www.nikodym.cl/?ref=demo-reporte#contact"
            target="_blank"
            rel="noreferrer"
            className="text-eyebrow underline underline-offset-4 hover:no-underline"
          >
            Proponer un caso ↗
          </a>
        </p>
      </CardContent>
    </Card>
  )
}
