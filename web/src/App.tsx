import { useState } from "react"
import {
  ChartColumn,
  Database,
  FileText,
  Play,
  SlidersHorizontal,
  type LucideIcon,
} from "lucide-react"

import { AppSidebar } from "@/components/AppSidebar"
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

/** Las 5 secciones del flujo (SDD-23 §4.3). Shells vacíos hasta B23.4b/B23.5. */
const SECTIONS: SectionDef[] = [
  {
    value: "config",
    label: "Config",
    icon: SlidersHorizontal,
    title: "Editor del config",
    cardDescription:
      "Formulario auto-generado desde el schema de NikodymConfig.",
    empty:
      "Aquí vivirá el formulario declarativo: cada sección del config como grupo de campos, con validación por reconstrucción en el backend y config_hash en vivo.",
    tag: "B23.4b",
  },
  {
    value: "datos",
    label: "Datos",
    icon: Database,
    title: "Datos",
    cardDescription:
      "Elige un dataset sintético determinista para la corrida.",
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

function App() {
  const [active, setActive] = useState<string>(SECTIONS[0].value)
  const section = SECTIONS.find((s) => s.value === active) ?? SECTIONS[0]
  const Icon = section.icon

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <AppSidebar items={SECTIONS} active={active} onSelect={setActive} />

      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-4xl px-6 py-10 lg:px-10">
          {/* B23.6: <FlowStepper> visible solo en modo demo */}

          <header className="mb-8">
            <p className="mb-2 font-mono text-xs uppercase tracking-[0.18em] text-brand-cyan">
              config-driven
            </p>
            <h1 className="font-display text-2xl font-bold text-brand-offwhite sm:text-3xl">
              {section.title}
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              {section.cardDescription}
            </p>
          </header>

          {active === "config" ? (
            <ConfigTab />
          ) : active === "ejecutar" ? (
            <RunTab onNavigate={setActive} />
          ) : active === "resultados" ? (
            <ResultsTab onNavigate={setActive} />
          ) : (
            <Card className="shadow-card">
              <EmptyState
                icon={Icon}
                title="Próximamente"
                description={section.empty}
                tag={section.tag}
              />
            </Card>
          )}

          <p className="mt-8 font-mono text-xs text-brand-placeholder">
            Backend: {API_BASE}
          </p>
        </div>
      </main>
    </div>
  )
}

export default App
