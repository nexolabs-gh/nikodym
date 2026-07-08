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
import { EmptyState } from "@/components/EmptyState"
import { ResultsTab } from "@/components/ResultsTab"
import { RunTab } from "@/components/RunTab"
import { Card } from "@/components/ui/card"
import { API_BASE } from "@/lib/api"

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
    label: "Datos",
    icon: Table2,
    description: "Fuente, esquema, missing, target y partición del panel de datos.",
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
    label: "Datos",
    icon: Database,
    title: "Datos",
    cardDescription: "Elige un dataset sintético determinista para la corrida.",
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
    cardDescription: "HTML determinístico del reporte, descargable.",
    empty:
      "El reporte HTML determinístico (SDD-26) se servirá tal cual, junto al YAML canónico que reproduce la corrida por código.",
    tag: "B23.5",
  },
]

/** Árbol de navegación del sidebar: "Configuración" (con sus 7 sub-secciones) + el flujo. */
const NAV: NavItem[] = [
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
  ...SECTIONS.map((s) => ({ value: s.value, label: s.label, icon: s.icon })),
]

/** Sección de config activa (clave de schema) a partir del valor del sidebar, o `null`. */
function configKeyOf(active: string): string | null {
  return active.startsWith(CONFIG_PREFIX)
    ? active.slice(CONFIG_PREFIX.length)
    : null
}

function App() {
  const [active, setActive] = useState<string>(configValue(CONFIG_SECTIONS[0].key))

  // "config" a secas (p.ej. una navegación programática) cae en la primera sub-sección.
  const navigate = (value: string) =>
    setActive(value === "config" ? configValue(CONFIG_SECTIONS[0].key) : value)

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
      <AppSidebar items={NAV} active={active} onSelect={setActive} />

      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-4xl px-6 py-10 lg:px-10">
          <header className="mb-8">
            <p className="mb-2 font-mono text-xs uppercase tracking-[0.18em] text-brand-cyan">
              {eyebrow}
            </p>
            <h1 className="font-display text-2xl font-bold text-brand-offwhite sm:text-3xl">
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

          <p className="mt-8 font-mono text-xs text-brand-placeholder">
            Backend: {API_BASE}
          </p>
        </div>
      </main>
    </div>
  )
}

export default App
