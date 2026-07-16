import { useState } from "react"
import {
  Activity,
  Boxes,
  ChartColumn,
  Database,
  FileText,
  Gauge,
  ListFilter,
  Play,
  Scale,
  Sigma,
  SlidersHorizontal,
  Table2,
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
import { RunTab } from "@/components/RunTab"
import { Card } from "@/components/ui/card"
import { API_BASE, getPresetById } from "@/lib/api"
import { bootstrapOnce } from "@/lib/bootstrap"
import { DEMO_MODE } from "@/lib/demo"
import { useAppState } from "@/state/appStore"

interface SectionDef {
  value: string
  label: string
  icon: LucideIcon
  title: string
  cardDescription: string
  empty: string
  tag: string
}

/** Prefijo de las secciones de config en el sidebar: `config:<clave-de-schema>`. */
const CONFIG_PREFIX = "config:"
const configValue = (key: string) => `${CONFIG_PREFIX}${key}`

interface ConfigSectionDef {
  /** Clave de sección del schema (F1_SECTIONS). */
  key: string
  /** Etiqueta humana, on-brand (sidebar + encabezado). */
  label: string
  icon: LucideIcon
  /** Subtítulo del encabezado. */
  description: string
}

/**
 * Las 7 secciones del config F1 (B30): cada una es un item navegable del sidebar bajo
 * "Configuración" y muestra SOLO su formulario. El orden y las claves siguen a F1_SECTIONS
 * (`lib/schema.ts`); los labels son humanos (no "binning" → "Optimal Binning").
 */
const CONFIG_SECTIONS: ConfigSectionDef[] = [
  {
    key: "data",
    label: "Esquema y target",
    icon: Table2,
    description:
      "Cómo se interpreta el dataset cargado: esquema, tipos, target, missing y partición.",
  },
  {
    key: "binning",
    label: "Optimal Binning",
    icon: Boxes,
    description:
      "Binning óptimo (OptBinning): restricciones, monotonía, solver y salida.",
  },
  {
    key: "selection",
    label: "Selección de variables",
    icon: ListFilter,
    description:
      "Filtros de selección: IV, métricas univariadas, correlación, VIF y estabilidad.",
  },
  {
    key: "model",
    label: "Modelo",
    icon: Sigma,
    description: "Ajuste del modelo, inferencia, stepwise y política de signos de beta.",
  },
  {
    key: "scorecard",
    label: "Scorecard",
    icon: Gauge,
    description: "Escalado a puntaje: PDO, odds objetivo, rango y publicación.",
  },
  {
    key: "calibration",
    label: "Calibración",
    icon: Scale,
    description: "Calibración de PD: método, ancla y ajuste.",
  },
  {
    key: "performance",
    label: "Performance",
    icon: Activity,
    description: "Métricas de desempeño: columnas, población y deciles.",
  },
]

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
    tag: "B23.5",
  },
  {
    value: "ejecutar",
    label: "Ejecutar",
    icon: Play,
    title: "Ejecutar",
    cardDescription: "Dispara la corrida vía nikodym.run (síncrona).",
    empty:
      "El disparador de la corrida y su estado (done / failed con lineage) aparecerán aquí, sin cálculo propio en el front.",
    tag: "B23.5",
  },
  {
    value: "resultados",
    label: "Resultados",
    icon: ChartColumn,
    title: "Resultados",
    cardDescription: "Métricas, artefactos y visores de la corrida.",
    empty:
      "WoE/IV, coeficientes, KS/AUC/Gini, gains/lift, scorecard y calibración — solo formateo de artefactos ya materializados.",
    tag: "B23.5",
  },
  {
    value: "reporte",
    label: "Reporte",
    icon: FileText,
    title: "Reporte",
    cardDescription:
      "El informe de validación de tu última corrida: HTML, PDF, Word o base editable.",
    empty:
      "El reporte HTML determinístico (SDD-26) se servirá tal cual, junto al YAML canónico que reproduce la corrida por código.",
    tag: "B23.5",
  },
]

/**
 * Árbol de navegación del sidebar, en el orden del flujo real:
 * 1) Cargar datos (upload) → 2) Configuración (7 sub-secciones; la 1ª es la lectura/esquema)
 * → 3) Ejecutar → 4) Resultados → 5) Reporte. Cargar-datos va ARRIBA de la config porque
 * primero se trae el dataset y luego se configura cómo leerlo.
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
      icon: s.icon,
    })),
  },
  ...FLOW_SECTIONS.map((s) => ({ value: s.value, label: s.label, icon: s.icon })),
]

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
  const { setConfig, setDatasetId, setSelectedDataset, setSeed } = useAppState()

  // "config" a secas (p.ej. una navegación programática) cae en la primera sub-sección.
  const navigate = (value: string) =>
    setActive(value === "config" ? configValue(CONFIG_SECTIONS[0].key) : value)

  // Entrada desde el landing. SIN preset (build normal / CTA genérico): flujo completo, arranca en
  // Datos. CON preset (selector de demos de `demo.nikodym.cl`): resiembra ESE pipeline y entra
  // directo a Ejecutar, ya cargado y listo para correr —así el dominio elegido (p. ej. IFRS 9) no
  // queda enterrado tras el selector de Ejecutar—. `await bootstrapOnce()` garantiza que la siembra
  // estándar del provider ya ocurrió, para que su resolución no pise la elección un instante después.
  const enterDemo = async (presetId?: string) => {
    if (presetId) {
      await bootstrapOnce()
      try {
        const preset = await getPresetById(presetId)
        setConfig(structuredClone(preset.config))
        setDatasetId(preset.dataset_id)
        setSelectedDataset(null)
        setSeed({ kind: "preset", name: preset.name, datasetId: preset.dataset_id })
      } catch {
        /* no se pudo resembrar: sigue el preset estándar ya sembrado; la demo no rompe. */
      }
      setActive("ejecutar")
    } else {
      setActive(DATA_SECTION.value)
    }
    setView("workspace")
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
            <DatosTab onNavigate={navigate} />
          ) : active === "reporte" ? (
            <ReporteTab onNavigate={navigate} />
          ) : section ? (
            <Card className="shadow-card">
              <EmptyState
                icon={section.icon}
                title="Próximamente"
                description={section.empty}
                tag={section.tag}
              />
            </Card>
          ) : null}

          <p className="mt-8 font-mono text-xs text-muted-foreground">
            {DEMO_MODE
              ? "Modo demo · corrida real de Nikodym sobre un dataset sintético de ejemplo"
              : `Backend: ${API_BASE}`}
          </p>
        </div>
      </main>
    </div>
  )
}

export default App
