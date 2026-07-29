import { useEffect, useState } from "react"
import {
  Activity,
  Boxes,
  ChartColumn,
  Database,
  FileSignature,
  FileText,
  Gauge,
  GitCompare,
  Landmark,
  Layers,
  ListFilter,
  Play,
  Scale,
  Sigma,
  SlidersHorizontal,
  Table2,
  TrendingDown,
  Users,
  Waves,
  type LucideIcon,
} from "lucide-react"

import { AppSidebar, type NavItem } from "@/components/AppSidebar"
import { ConfigTab } from "@/components/ConfigTab"
import { DatosTab } from "@/components/DatosTab"
import { EmptyState } from "@/components/EmptyState"
import { FlowStepper, type FlowStep } from "@/components/FlowStepper"
import { LandingLauncher } from "@/components/LandingLauncher"
import { ReporteTab } from "@/components/ReporteTab"
import { ResultsTab } from "@/components/ResultsTab"
import { applyPreset, RunTab } from "@/components/RunTab"
import { Card } from "@/components/ui/card"
import { API_BASE, getPresetById } from "@/lib/api"
import { bootstrapOnce } from "@/lib/bootstrap"
import { DEMO_MODE } from "@/lib/demo-runtime"
import {
  candidateFieldIds,
  sectionIsEditable,
  sectionOfPath,
} from "@/lib/preflight"
import { CONFIG_SECTIONS } from "@/lib/schema"
import { useAppState } from "@/state/appStore"

interface SectionDef {
  value: string
  label: string
  icon: LucideIcon
  title: string
  cardDescription: string
  empty: string
}

/** Prefijo de las secciones de config en el sidebar: `config:<clave-de-schema>`. */
const CONFIG_PREFIX = "config:"
const configValue = (key: string) => `${CONFIG_PREFIX}${key}`

/**
 * Icono de cada sección de configuración. Vive aquí y no junto al catálogo (`lib/schema.ts`) para
 * que ese módulo no importe `lucide-react` y siga siendo lógica pura, testeable sin React.
 */
const SECTION_ICONS: Record<string, LucideIcon> = {
  data: Table2,
  binning: Boxes,
  selection: ListFilter,
  model: Sigma,
  scorecard: Gauge,
  calibration: Scale,
  performance: Activity,
  stability: Waves,
  survival: TrendingDown,
  provisioning_cmf: Landmark,
  provisioning_internal: Users,
  provisioning_ifrs9: Layers,
  provisioning: GitCompare,
  // `FileSignature` y no `FileText`: ése ya es el icono del paso «Reporte» del flujo, que MUESTRA el
  // informe. Esta sección lo CONFIGURA —incluida la portada que firma la institución—, y dos
  // entradas del sidebar con el mismo icono se leen como la misma pantalla.
  report: FileSignature,
}

/** Secciones del flujo de nivel-app (SDD-23 §4.3), sin "Configuración" (que ahora se anida). */
const SECTIONS: SectionDef[] = [
  {
    value: "datos",
    label: "Cargar datos",
    icon: Database,
    title: "Cargar datos",
    cardDescription:
      "Elige un dataset de ejemplo o sube el tuyo (CSV, Excel o Parquet).",
    empty:
      "El selector de datasets sintéticos (id, columnas, roles) se cableará a data.load.source, sin duplicar lógica de dominio.",
  },
  {
    value: "ejecutar",
    label: "Ejecutar",
    icon: Play,
    title: "Ejecutar",
    cardDescription: "Dispara la corrida vía nikodym.run (síncrona).",
    empty:
      "El disparador de la corrida y su estado (done / failed con lineage) aparecerán aquí, sin cálculo propio en el front.",
  },
  {
    value: "resultados",
    label: "Resultados",
    icon: ChartColumn,
    title: "Resultados",
    cardDescription: "Métricas, artefactos y visores de la corrida.",
    empty:
      "WoE/IV, coeficientes, KS/AUC/Gini, gains/lift, scorecard y calibración — solo formateo de artefactos ya materializados.",
  },
  {
    value: "reporte",
    label: "Reporte",
    icon: FileText,
    title: "Reporte",
    cardDescription:
      "El informe de validación de tu última corrida: HTML, PDF, Word o base editable.",
    empty:
      "El informe determinístico se servirá tal cual, junto al YAML canónico que reproduce la corrida por código.",
  },
]

/**
 * Árbol de navegación del sidebar, en el orden del flujo real:
 * 1) Cargar datos (upload) → 2) Configuración (las sub-secciones de `CONFIG_SECTIONS`; la 1ª es la
 * lectura/esquema) → 3) Ejecutar → 4) Resultados → 5) Reporte. Cargar-datos va ARRIBA de la config
 * porque primero se trae el dataset y luego se configura cómo leerlo.
 */
const [DATA_SECTION, ...FLOW_SECTIONS] = SECTIONS
const NAV: NavItem[] = [
  { value: DATA_SECTION.value, label: DATA_SECTION.label, icon: DATA_SECTION.icon },
  {
    value: "config",
    label: "Configuración",
    icon: SlidersHorizontal,
    children: CONFIG_SECTIONS.map((s) => ({
      value: configValue(s.key),
      label: s.label,
      icon: SECTION_ICONS[s.key] ?? SlidersHorizontal,
    })),
  },
  ...FLOW_SECTIONS.map((s) => ({ value: s.value, label: s.label, icon: s.icon })),
]

/**
 * Control **visible** que corresponde a `id`, o `null` si no hay ninguno en el DOM.
 *
 * ⚠️ No basta `getElementById`, y se midió en vivo: un campo opcional **apagado** se pinta como un
 * `<span role="switch">` («Activar …») y el `id` del path lo lleva un `<input type="checkbox">`
 * interno del componente, con `aria-hidden` y `position: fixed`. Enfocar ése no mueve la página a
 * ninguna parte y el salto falla en silencio — justo en los campos opcionales, que son la mayoría
 * de los que el preflight señala (`index_col`, `temporal_column`, `cohort_col`).
 *
 * Por eso se descartan los `aria-hidden` y se prefiere el primer nodo enfocable; si sólo queda el
 * oculto, se cae al switch visible de su mismo grupo, que es el control que el usuario debe tocar
 * para poder escribir el nombre.
 */
function controlVisible(id: string): HTMLElement | null {
  const nodos = [
    ...document.querySelectorAll<HTMLElement>(`[id="${CSS.escape(id)}"]`),
  ]
  const enfocable = nodos.find(
    (el) => el.getAttribute("aria-hidden") !== "true" && el.tabIndex >= 0,
  )
  if (enfocable) return enfocable
  const oculto = nodos[0]
  if (!oculto) return null
  return (
    oculto.parentElement?.querySelector<HTMLElement>('[role="switch"]') ?? oculto
  )
}

/** Sección de config activa (clave de schema) a partir del valor del sidebar, o `null`. */
function configKeyOf(active: string): string | null {
  return active.startsWith(CONFIG_PREFIX)
    ? active.slice(CONFIG_PREFIX.length)
    : null
}

/**
 * Los 5 pasos del flujo, tal como los ve el usuario (el sidebar los desglosa; el stepper los
 * resume). Configuración es OPCIONAL: el config estándar se siembra y valida solo al entrar
 * (`lib/bootstrap.ts`), así que se puede ir de Datos a Ejecutar sin pasar por ahí.
 */
const FLOW_STEPS: (FlowStep & { value: string })[] = [
  { value: DATA_SECTION.value, label: "Datos" },
  { value: "config", label: "Configuración", optional: true },
  { value: "ejecutar", label: "Ejecutar" },
  { value: "resultados", label: "Resultados" },
  { value: "reporte", label: "Reporte" },
]

/** Paso del stepper que corresponde a la sección abierta (cualquier `config:*` es el paso 2). */
function stepIndexOf(active: string): number {
  const value = configKeyOf(active) === null ? active : "config"
  const index = FLOW_STEPS.findIndex((step) => step.value === value)
  return index === -1 ? 0 : index
}

function App() {
  // Nivel-0: la landing/launcher se ve ANTES del workspace; entrar la deja atrás.
  const [view, setView] = useState<"landing" | "workspace">("landing")
  // Entra por "Cargar datos": el flujo mental es traer el dataset antes de configurar cómo leerlo.
  const [active, setActive] = useState<string>(DATA_SECTION.value)
  const {
    setConfig,
    setDatasetId,
    setSelectedDataset,
    setSeed,
    setResults,
    setLastRun,
    focusField,
    setFocusField,
  } = useAppState()

  // Atiende el foco que pidió un aviso del preflight (D-PRE-8). Vive AQUÍ y no en `ConfigTab` por
  // dos razones: esa pestaña es un editor puro sin efectos —gate de `bootstrap.test.ts`, que
  // protege la regresión UX1— y este efecto corre tras el commit del árbol completo, con el
  // formulario de la sección ya montado.
  //
  // Se prueban los candidatos de `candidateFieldIds` en orden: el campo exacto y, si el formulario
  // no expande esa lista, el control que edita la lista entera. Si ninguno está en el DOM se
  // limpia igual y el usuario queda en la sección correcta, que es el fallback declarado.
  useEffect(() => {
    if (focusField === null) return
    for (const id of candidateFieldIds(focusField)) {
      const el = controlVisible(id)
      if (el === null) continue
      el.scrollIntoView({ block: "center", behavior: "smooth" })
      el.focus({ preventScroll: true })
      break
    }
    setFocusField(null)
  }, [focusField, setFocusField])

  // "config" a secas (p.ej. una navegación programática) cae en la primera sub-sección.
  const navigate = (value: string) =>
    setActive(value === "config" ? configValue(CONFIG_SECTIONS[0].key) : value)

  // Salto desde un aviso del preflight al campo que lo causa (D-PRE-8): abre la sección de config
  // que le corresponde y deja pedido el foco, que atiende `ConfigTab` cuando ya montó su
  // formulario. La navegación vive aquí —es la dueña de `active`—; el foco viaja por el store
  // porque quien lo pide (el aviso en Datos) y quien lo atiende están en pestañas distintas.
  const jumpToField = (path: string) => {
    const seccion = sectionOfPath(path)
    if (!sectionIsEditable(seccion)) return // sin pestaña que abrir; el aviso ya lo dice
    setActive(configValue(seccion))
    setFocusField(path) // el path CRUDO: la traducción a `id` la resuelve el efecto de foco
  }

  // Entrada desde el landing. SIN preset (build normal / CTA genérico): flujo completo, arranca en
  // Datos. CON preset (selector de demos de `demo.nikodym.cl`): resiembra ESE pipeline y entra
  // directo a Ejecutar, ya cargado y listo para correr —así el dominio elegido (p. ej. IFRS 9) no
  // queda enterrado tras el selector de Ejecutar—. `applyPreset` además CORTA con la corrida anterior
  // (results/lastRun) para no mostrar el dominio previo; el outcome vive en RunTab, que monta en idle.
  // `await bootstrapOnce()` garantiza que la siembra estándar del provider ya ocurrió, para que su
  // resolución no pise la elección un instante después.
  const enterDemo = async (presetId?: string) => {
    if (presetId) {
      await bootstrapOnce()
      try {
        await applyPreset(presetId, {
          getPreset: getPresetById,
          setConfig,
          setDatasetId,
          setSelectedDataset,
          setSeed,
          setResults,
          setLastRun,
          resetOutcome: () => {},
        })
      } catch {
        /* no se pudo resembrar: sigue el preset estándar ya sembrado; la demo no rompe. */
      }
      setActive("ejecutar")
    } else {
      setActive(DATA_SECTION.value)
    }
    setView("workspace")
    // El landing y el workspace comparten el scroll de la ventana, así que entrar desde una CTA
    // que está a mitad de página deja la app abierta por su mitad (medido: `scrollY = 215`, la
    // barra de pasos fuera de cuadro). Cambiar de vista no es navegar, así que el navegador no
    // lo resetea por su cuenta.
    window.scrollTo(0, 0)
  }

  if (view === "landing") {
    return <LandingLauncher onEnter={enterDemo} />
  }

  const configKey = configKeyOf(active)
  const configSection = configKey
    ? CONFIG_SECTIONS.find((s) => s.key === configKey)
    : undefined
  const section = SECTIONS.find((s) => s.value === active)

  const eyebrow = configSection ? "Configuración" : "config-driven"
  const title = configSection?.label ?? section?.title ?? ""
  const description = configSection?.description ?? section?.cardDescription ?? ""

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <AppSidebar
        items={NAV}
        active={active}
        onSelect={setActive}
        onHome={() => setView("landing")}
      />

      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-4xl px-6 py-10 lg:px-10">
          <FlowStepper steps={FLOW_STEPS} current={stepIndexOf(active)} />

          <header className="mb-8">
            <p className="mb-2 font-mono text-xs uppercase tracking-[0.18em] text-eyebrow">
              {eyebrow}
            </p>
            <h1 className="font-display text-2xl font-bold text-foreground sm:text-3xl">
              {title}
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              {description}
            </p>
          </header>

          {configKey ? (
            <ConfigTab section={configKey} />
          ) : active === "ejecutar" ? (
            <RunTab onNavigate={navigate} />
          ) : active === "resultados" ? (
            <ResultsTab onNavigate={navigate} />
          ) : active === "datos" ? (
            <DatosTab onNavigate={navigate} onJumpToField={jumpToField} />
          ) : active === "reporte" ? (
            <ReporteTab onNavigate={navigate} />
          ) : section ? (
            <Card className="shadow-card">
              <EmptyState
                icon={section.icon}
                title="Próximamente"
                description={section.empty}
              />
            </Card>
          ) : null}

          <p className="mt-8 font-mono text-xs text-muted-foreground">
            {DEMO_MODE
              ? "Modo demo · corrida real de Nikodym sobre un dataset sintético de ejemplo"
              : `Backend: ${API_BASE || "same-origin"}`}
          </p>
        </div>
      </main>
    </div>
  )
}

export default App
