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
import { jobSkeleton, loadJobs, sectionsOfJob, type Job } from "@/lib/jobs"
import { CONFIG_SECTIONS, type ConfigSectionDef } from "@/lib/schema"
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
    // El orden del subtítulo sigue al de la pantalla (D-JOB-2): primero el tuyo.
    cardDescription:
      "Sube tu dataset (CSV, Excel o Parquet), o elige uno de ejemplo.",
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
 * 1) Cargar datos (upload) → 2) Configuración (las sub-secciones del trabajo elegido; la 1ª es la
 * lectura/esquema) → 3) Ejecutar → 4) Resultados → 5) Reporte. Cargar-datos va ARRIBA de la config
 * porque primero se trae el dataset y luego se configura cómo leerlo.
 *
 * 🔴 **Las sub-secciones las decide el TRABAJO** (D-JOB-1). Hasta ahora esto mapeaba
 * `CONFIG_SECTIONS` entera, sin un solo filtro: quien venía a un scorecard veía IFRS 9, survival y
 * CMF, y un área que sólo hace LGD veía binning ajeno. El trabajo manda y se ve lo necesario, sin
 * grupo de «otras secciones» ni avisos (D-JOB-17). Sin trabajo se ven todas, que es lo que
 * corresponde a quien trajo un config —archivo o ejemplo— que no calza con ninguno.
 */
const [DATA_SECTION, ...FLOW_SECTIONS] = SECTIONS

function navItems(secciones: ConfigSectionDef[]): NavItem[] {
  return [
    { value: DATA_SECTION.value, label: DATA_SECTION.label, icon: DATA_SECTION.icon },
    {
      value: "config",
      label: "Configuración",
      icon: SlidersHorizontal,
      children: secciones.map((s) => ({
        value: configValue(s.key),
        label: s.label,
        icon: SECTION_ICONS[s.key] ?? SlidersHorizontal,
      })),
    },
    ...FLOW_SECTIONS.map((s) => ({ value: s.value, label: s.label, icon: s.icon })),
  ]
}

/**
 * Control **visible** que corresponde a `id`, o `null` si no hay ninguno en el DOM.
 *
 * ⚠️ No basta `getElementById`, y se midió en vivo: un campo opcional **apagado** no tiene input de
 * valor —sólo su switch «Activar …»—, así que el `id` del path no existe en el DOM. Enfocar la nada
 * hace fallar el salto en silencio, justo en los campos opcionales, que son la mayoría de los que
 * el preflight señala (`index_col`, `temporal_column`, `cohort_col`).
 *
 * Por eso el switch de un campo opcional declara `data-field-path` con el path de su campo: es el
 * control que el usuario tiene que tocar para poder escribir el nombre. Antes esto se resolvía
 * poniéndole al switch el mismo `id` que al input, lo que dejaba **dos elementos con el mismo `id`**
 * en la página y obligaba a filtrar por `aria-hidden`; el atributo explícito dice lo mismo sin
 * romper la unicidad del `id`.
 */
function controlVisible(id: string): HTMLElement | null {
  const nodos = [
    ...document.querySelectorAll<HTMLElement>(`[id="${CSS.escape(id)}"]`),
  ]
  const enfocable = nodos.find(
    (el) => el.getAttribute("aria-hidden") !== "true" && el.tabIndex >= 0,
  )
  if (enfocable) return enfocable
  const activador = document.querySelector<HTMLElement>(
    `[data-field-path="${CSS.escape(id)}"]`,
  )
  if (activador) return activador
  const oculto = nodos[0]
  if (oculto) {
    return (
      oculto.parentElement?.querySelector<HTMLElement>('[role="switch"]') ??
      oculto
    )
  }
  // Degradación HACIA ABAJO: el path nombra un objeto que no tiene control propio, sino varios
  // hijos. Medido con las decisiones obligatorias (D-OBL-8): `data.target.bad_rule` no existe en el
  // DOM —existen `…bad_rule.all_of` y `…bad_rule.any_of`—, así que el salto caía al botón que lo
  // disparó. `candidateFieldIds` sólo degrada hacia arriba (recorta listas), que es el caso
  // simétrico y no cubre éste. Se enfoca el primer control de dentro, que es donde el usuario
  // empieza a contestar de todos modos.
  return document.querySelector<HTMLElement>(
    `[id^="${CSS.escape(id)}."][tabindex]:not([aria-hidden="true"]), ` +
      `input[id^="${CSS.escape(id)}."]:not([aria-hidden="true"]), ` +
      `button[id^="${CSS.escape(id)}."]:not([aria-hidden="true"])`,
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
 * resume).
 *
 * ⚠️ **Configuración es opcional SÓLO con un ejemplo cargado**, y el matiz lo trajo D-JOB-2. Un
 * preset trae parámetros curados y su dataset, así que de Datos se puede ir a Ejecutar sin pasar por
 * ahí. En una sesión vacía todas las secciones llegan apagadas; y con un trabajo recién elegido
 * (D-JOB-16) las secciones existen pero falta lo que sólo decide el usuario sobre sus datos —qué es
 * un incumplimiento, cómo particionar—. En esos dos estados el rótulo «OPCIONAL» señalaría como
 * saltable justo el paso que falta.
 */
function flowSteps(configOpcional: boolean): (FlowStep & { value: string })[] {
  return [
    { value: DATA_SECTION.value, label: "Datos" },
    { value: "config", label: "Configuración", optional: configOpcional },
    { value: "ejecutar", label: "Ejecutar" },
    { value: "resultados", label: "Resultados" },
    { value: "reporte", label: "Reporte" },
  ]
}

/** Orden de los pasos; el rótulo `optional` no lo cambia, así que la búsqueda vive aparte. */
const FLOW_ORDER = ["datos", "config", "ejecutar", "resultados", "reporte"]

/** Paso del stepper que corresponde a la sección abierta (cualquier `config:*` es el paso 2). */
function stepIndexOf(active: string): number {
  const value = configKeyOf(active) === null ? active : "config"
  const index = FLOW_ORDER.indexOf(value)
  return index === -1 ? 0 : index
}

function App() {
  // Nivel-0: la landing/launcher se ve ANTES del workspace; entrar la deja atrás.
  const [view, setView] = useState<"landing" | "workspace">("landing")
  // Entra por "Cargar datos": el flujo mental es traer el dataset antes de configurar cómo leerlo.
  const [active, setActive] = useState<string>(DATA_SECTION.value)
  const {
    seed,
    job,
    setJob,
    setConfig,
    setDatasetId,
    setSelectedDataset,
    setSeed,
    setResults,
    setLastRun,
    focusField,
    setFocusField,
  } = useAppState()

  // Las secciones que existen esta sesión (D-JOB-1). Sin trabajo elegido son todas.
  const configSections = sectionsOfJob(job)

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

  // Si la sección abierta deja de pertenecer al trabajo activo, se cae a la primera del trabajo.
  // Es una guarda, no una rama esperada —`enterJob` vuelve a Datos al elegir—, pero sin ella un
  // camino futuro que cambie de trabajo con Configuración abierta dejaría al usuario en una
  // pestaña que el sidebar ya no ofrece: ni encabezado ni forma de salir salvo el sidebar.
  useEffect(() => {
    const abierta = configKeyOf(active)
    if (abierta === null || configSections.length === 0) return
    if (!configSections.some((s) => s.key === abierta)) {
      setActive(configValue(configSections[0].key))
    }
  }, [active, configSections])

  // "config" a secas (p.ej. una navegación programática) cae en la primera sub-sección DEL TRABAJO:
  // con el catálogo entero caería siempre en `data`, que puede no ser la primera del trabajo activo.
  const navigate = (value: string) =>
    setActive(
      value === "config"
        ? configValue((configSections[0] ?? CONFIG_SECTIONS[0]).key)
        : value,
    )

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
  // queda enterrado tras el selector de Ejecutar—. `applyPreset` además deja la sesión en el trabajo
  // del ejemplo (D-JOB-17) y CORTA con la corrida anterior (results/lastRun) para no mostrar el
  // dominio previo; el outcome vive en RunTab, que monta en idle.
  // `await bootstrapOnce()` garantiza que la siembra estándar del provider ya ocurrió, para que su
  // resolución no pise la elección un instante después.
  //
  // ⚠️ Aquí el cambio de trabajo NO se avisa, y es la única de las tres puertas al ejemplo donde no
  // se hace: `enterDemo` sólo se alcanza desde el landing, o sea que el usuario está ENTRANDO y no
  // hay ningún sidebar previo al que su elección contradiga. El aviso de D-JOB-17 explica una
  // navegación que cambia bajo los pies; en el arranque no habría nada que explicar y sería ruido.
  const enterDemo = async (presetId?: string) => {
    if (presetId) {
      await bootstrapOnce()
      try {
        await applyPreset(presetId, job, {
          getPreset: getPresetById,
          loadJobs,
          setConfig,
          setJob,
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

  /**
   * Entrada por un TRABAJO (D-JOB-1/16): fija qué secciones existen esta sesión y siembra el
   * esqueleto de ese trabajo —sus secciones con los defaults del motor y NINGÚN dataset—.
   *
   * El esqueleto es lo que conserva «no hace falta pasar por Configuración» sin sembrar la demo: el
   * primer gesto sigue siendo traer tu archivo, y el preflight dice qué corregir. Con el config del
   * todo vacío, un scorecard exigiría activar nueve secciones a mano antes de poder correr.
   */
  const enterJob = async (elegido: Job) => {
    const { schema: cargado } = await bootstrapOnce()
    setJob(elegido)
    setConfig((actual) =>
      jobSkeleton(actual, elegido, cargado.payload.effective_defaults),
    )
    setSeed({ kind: "job", jobId: elegido.id, label: elegido.label })
    // El trabajo cambia el dominio: la corrida anterior ya no le corresponde (mismo corte que
    // `applyPreset`, y por el mismo P0 de lineage mixto en Resultados y Reporte).
    setResults(null)
    setLastRun(null)
    setActive(DATA_SECTION.value)
    setView("workspace")
    // El landing y el workspace comparten el scroll de la ventana, así que entrar desde una CTA
    // que está a mitad de página deja la app abierta por su mitad (medido: `scrollY = 215`, la
    // barra de pasos fuera de cuadro). Cambiar de vista no es navegar, así que el navegador no
    // lo resetea por su cuenta.
    window.scrollTo(0, 0)
  }

  if (view === "landing") {
    return <LandingLauncher onEnter={enterDemo} onPickJob={enterJob} />
  }

  const configKey = configKeyOf(active)
  // Se busca en las secciones DEL TRABAJO: si la activa ya no pertenece —porque el usuario cambió
  // de trabajo con esa pestaña abierta— no hay encabezado que pintar y cae al `EmptyState`, en vez
  // de mostrar el título de una sección que el sidebar ya no ofrece.
  const configSection = configKey
    ? configSections.find((s) => s.key === configKey)
    : undefined
  const section = SECTIONS.find((s) => s.value === active)

  const eyebrow = configSection ? "Configuración" : "config-driven"
  const title = configSection?.label ?? section?.title ?? ""
  const description = configSection?.description ?? section?.cardDescription ?? ""

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <AppSidebar
        items={navItems(configSections)}
        active={active}
        onSelect={setActive}
        onHome={() => setView("landing")}
      />

      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-4xl px-6 py-10 lg:px-10">
          <FlowStepper
            steps={flowSteps(seed?.kind === "preset")}
            current={stepIndexOf(active)}
          />

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
