import { useEffect, useState } from "react"
import { ArrowRight, ArrowUpRight, Check, Copy } from "lucide-react"

import { listPresets, type PresetSummary } from "@/lib/api"
import { NikodymMark } from "@/components/NikodymMark"
import { ThemeToggle } from "@/components/ThemeToggle"
import {
  CAPITULOS,
  CODIGO,
  DOMINIOS,
  GAINS_HOLDOUT,
  METRICAS,
  PIPELINE,
  SALVEDADES,
  TESTS_DOMINIOS,
  TESTS_SUITE,
} from "@/components/landing-evidence"
import { DEMO_MODE } from "@/lib/demo"
import { presetDisplay } from "@/lib/presentation"
import { cn } from "@/lib/utils"

/**
 * Landing / launcher de nivel-0. Rediseño 2026-07-13: el motor completo, no solo el scorecard.
 *
 * Voz: el documento técnico que el propio motor produce (secciones §, grid estricto, cifras en
 * mono, reglas finas). NO es una landing SaaS: quien llega es un analista de riesgo evaluando si
 * esto le sirve para un entregable que va a Validación, y a ese público lo convence la evidencia,
 * no el marketing.
 *
 * El mensaje que la página sostiene: **los seis dominios ya calculan; lo que falta es la
 * interfaz**. Es más fuerte que "próximamente" y, a diferencia de un roadmap, es verificable —por
 * eso §1 (el motor) va antes que el pipeline del scorecard: si el titular promete seis dominios y
 * el pago está seis pantallas abajo, la página incumple su propio titular.
 *
 * Dos reglas duras, ambas aprendidas de un verificador que intentó refutar este copy:
 *
 * 1. **El H1 no se recorta jamás a una línea** (ni en OG-image, ni en meta description, ni en
 *    mobile). "IFRS 9, CMF y stress ya los calcula el motor" sin su segunda línea deja de ser
 *    honesto: la confesión y la promesa viajan juntas o no viajan.
 * 2. **El CTA depende de DEMO_MODE.** En `demo.nikodym.cl` la app NO calcula: sirve los fixtures
 *    verbatim de una corrida real (ver `lib/demo.ts`). Ofrecer ahí "Construir un scorecard" sería
 *    prometer lo que esa pantalla no puede entregar.
 *
 * Regla de siempre: cada cifra de esta pantalla sale de una corrida REAL o de un conteo medido
 * (ver `landing-evidence.ts`). Cero lógica de dominio: solo navegación.
 */

const DOCS_URL = "https://docs.nikodym.cl"
const PYPI_CMD = "pip install nikodym"

/**
 * Consultora que construye el motor. La ancla es `#contact` (en inglés): con `#contacto` la página
 * carga igual pero no scrollea, y el visitante aterriza en el hero sin enterarse. El `?ref` va
 * ANTES del `#`, o queda dentro del fragmento y no llega al servidor.
 */
const CASO_URL = "https://www.nikodym.cl/?ref=demo#contact"
const CASO_URL_FOOTER = "https://www.nikodym.cl/?ref=demo-footer#contact"

/** Numeración de sección: la voz del documento. */
function Seccion({
  id,
  titulo,
  children,
}: {
  id: string
  titulo: string
  children: React.ReactNode
}) {
  return (
    <section className="border-t border-border py-14 lg:py-20">
      <div className="mb-8 flex items-baseline gap-4">
        <span className="font-mono text-sm text-brand-accent-dark">{id}</span>
        <h2 className="font-display text-lg font-bold tracking-tight text-foreground">
          {titulo}
        </h2>
      </div>
      {children}
    </section>
  )
}

/** `pip install nikodym`, copiable. El primer gesto real de un técnico. */
function ComandoCopiable({ className }: { className?: string }) {
  const [copiado, setCopiado] = useState(false)

  const copiar = () => {
    void navigator.clipboard?.writeText(PYPI_CMD).then(() => {
      setCopiado(true)
      window.setTimeout(() => setCopiado(false), 1600)
    })
  }

  return (
    <button
      type="button"
      onClick={copiar}
      aria-label={`Copiar «${PYPI_CMD}» al portapapeles`}
      className={cn(
        "group inline-flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3",
        "font-mono text-sm text-foreground transition-colors hover:border-brand-accent-dark/50",
        className,
      )}
    >
      <span className="select-none text-muted-foreground">$</span>
      {PYPI_CMD}
      {copiado ? (
        <Check className="size-3.5 text-eyebrow" aria-hidden="true" />
      ) : (
        <Copy
          className="size-3.5 text-muted-foreground transition-colors group-hover:text-foreground"
          aria-hidden="true"
        />
      )}
    </button>
  )
}

const CLASE_TOKEN: Record<string, string> = {
  kw: "text-brand-accent-dark",
  fn: "text-eyebrow",
  str: "text-eyebrow",
  cm: "text-muted-foreground/70",
  id: "text-foreground",
  p: "text-muted-foreground",
}

/** El quickstart real, con el cromo de un archivo. La evidencia que un técnico sí lee. */
function BloqueCodigo() {
  return (
    <figure className="overflow-hidden rounded-xl border border-border bg-card shadow-card">
      <figcaption className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <span className="font-mono text-[0.7rem] text-muted-foreground">quickstart.py</span>
        <span className="font-mono text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
          Python 3.11+
        </span>
      </figcaption>
      <pre className="overflow-x-auto px-4 py-4 font-mono text-[0.68rem] leading-[1.7] sm:text-[0.76rem]">
        <code>
          {CODIGO.map((linea, i) => (
            <span key={i} className="block min-h-[1.7em]">
              {linea.map((tok, j) => (
                <span key={j} className={CLASE_TOKEN[tok.c]}>
                  {tok.t}
                </span>
              ))}
            </span>
          ))}
        </code>
      </pre>
    </figure>
  )
}

/**
 * Curva de gains de la corrida real (holdout), dibujada a mano en SVG.
 * A propósito NO usa Recharts: no vale cargar la librería de charts en la primera pantalla.
 */
function CurvaGains() {
  const W = 360
  const H = 240
  const IZQ = 34
  const DER = 10
  const ARR = 12
  const ABA = 26

  const px = (decil: number) => IZQ + (decil / 10) * (W - IZQ - DER)
  const py = (cap: number) => H - ABA - (cap / 100) * (H - ABA - ARR)

  const puntos = [{ decil: 0, capturado: 0 }, ...GAINS_HOLDOUT]
  const coords = puntos.map((p) => `${px(p.decil)},${py(p.capturado)}`)
  const area = `M ${coords.join(" L ")} L ${px(10)},${py(0)} Z`
  const primero = GAINS_HOLDOUT[0]

  return (
    <figure className="rounded-xl border border-border bg-card p-5 shadow-card">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label="Curva de gains de la corrida de demostración sobre la partición holdout: el primer decil de score concentra el 21,3 % de los incumplimientos, y la curva domina a la diagonal de un modelo aleatorio en todo el recorrido."
      >
        <defs>
          <linearGradient id="gains-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--brand-accent-dark)" stopOpacity="0.28" />
            <stop offset="100%" stopColor="var(--brand-accent-dark)" stopOpacity="0.03" />
          </linearGradient>
        </defs>

        {/* Retícula del papel técnico, con el eje rotulado */}
        {[0, 50, 100].map((v) => (
          <g key={v}>
            <line
              x1={IZQ}
              y1={py(v)}
              x2={W - DER}
              y2={py(v)}
              stroke="currentColor"
              strokeWidth="0.5"
              className="text-border"
            />
            <text
              x={IZQ - 8}
              y={py(v) + 3}
              textAnchor="end"
              className="fill-muted-foreground font-mono"
              style={{ fontSize: "8px" }}
            >
              {v}%
            </text>
          </g>
        ))}

        {/* Referencia: un modelo que no discrimina nada */}
        <line
          x1={px(0)}
          y1={py(0)}
          x2={px(10)}
          y2={py(100)}
          stroke="currentColor"
          strokeWidth="1"
          strokeDasharray="3 3"
          className="text-muted-foreground/50"
        />
        <text
          x={px(7.1)}
          y={py(64)}
          className="fill-muted-foreground/70 font-mono"
          style={{ fontSize: "7.5px" }}
        >
          sin modelo
        </text>

        <path d={area} fill="url(#gains-fill)" />
        <polyline
          points={coords.join(" ")}
          fill="none"
          stroke="var(--brand-accent-dark)"
          strokeWidth="2.25"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {GAINS_HOLDOUT.map((p) => (
          <circle
            key={p.decil}
            cx={px(p.decil)}
            cy={py(p.capturado)}
            r="2.5"
            fill="var(--brand-accent-dark)"
          />
        ))}

        {/* El dato que un analista busca primero: cuánto captura el peor decil */}
        <circle
          cx={px(primero.decil)}
          cy={py(primero.capturado)}
          r="4.5"
          fill="none"
          stroke="var(--brand-accent-dark)"
          strokeWidth="1.25"
        />
        <text
          x={px(primero.decil) + 9}
          y={py(primero.capturado) + 3}
          className="fill-foreground font-mono"
          style={{ fontSize: "8.5px" }}
        >
          {`${primero.capturado.toString().replace(".", ",")} % en el decil 1`}
        </text>

        {[1, 5, 10].map((d) => (
          <text
            key={d}
            x={px(d)}
            y={H - 9}
            textAnchor="middle"
            className="fill-muted-foreground font-mono"
            style={{ fontSize: "8px" }}
          >
            {d}
          </text>
        ))}
      </svg>
      <figcaption className="mt-3 flex items-center justify-between font-mono text-[0.68rem] text-muted-foreground">
        <span>Captura de incumplimientos · holdout</span>
        <span>Decil de score →</span>
      </figcaption>
    </figure>
  )
}

/**
 * Selector de demos (SOLO en `demo.nikodym.cl`): una card por preset empaquetado (`listPresets()`),
 * para ELEGIR qué área ver sin enterrarla en el selector de Ejecutar. Al elegir una, entra al
 * workspace en Ejecutar con ese pipeline ya cargado. Data-driven: si mañana hay más presets en la
 * demo, aparecen aquí solos. Falla en silencio (sin catálogo no se muestra; el hero conserva el
 * comando `pip`). Título, garantía y blurb salen de la capa de presentación (`presetDisplay`), no
 * del nombre/descripción crudos del fixture: así landing y workspace muestran el mismo copy limpio.
 */
function DemoSelector({ onPick }: { onPick: (presetId: string) => void }) {
  const [presets, setPresets] = useState<PresetSummary[]>([])

  useEffect(() => {
    let alive = true
    void listPresets()
      .then((res) => {
        if (alive) setPresets(res.presets)
      })
      .catch(() => {
        /* sin catálogo: no se muestra el selector; el resto del hero sigue igual. */
      })
    return () => {
      alive = false
    }
  }, [])

  if (presets.length === 0) return null

  return (
    <div className="space-y-3">
      <p className="font-mono text-xs uppercase tracking-[0.18em] text-eyebrow">
        Elige una demo
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {presets.map((p) => {
          const { title, garantia, blurb } = presetDisplay(p)
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => onPick(p.id)}
              className={cn(
                "group flex h-full flex-col gap-2 rounded-xl border border-border bg-card p-4 text-left",
                "shadow-card outline-none transition-all hover:-translate-y-0.5 hover:border-brand-accent-dark/50",
                "focus-visible:border-brand-accent-dark focus-visible:ring-3 focus-visible:ring-brand-accent-dark/40",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="font-display font-bold leading-snug text-foreground">
                  {title}
                </span>
                <span
                  className={cn(
                    "shrink-0 rounded-full border px-2 py-0.5 font-mono text-[0.6rem] uppercase tracking-[0.1em]",
                    garantia === "experimental"
                      ? "border-amber-400/30 bg-amber-400/[0.06] text-amber-200/90"
                      : "border-eyebrow/30 bg-eyebrow/[0.06] text-eyebrow",
                  )}
                >
                  {garantia}
                </span>
              </div>
              <span className="line-clamp-3 text-xs leading-relaxed text-muted-foreground">
                {blurb}
              </span>
              <span className="mt-auto inline-flex items-center gap-1.5 pt-1 font-mono text-xs text-brand-accent-dark">
                Ver esta demo
                <ArrowRight
                  className="size-3.5 transition-transform group-hover:translate-x-0.5"
                  aria-hidden="true"
                />
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

/**
 * Pantalla de nivel-0: `onEnter` entra al workspace. Sin argumento → flujo completo (arranca en
 * Datos, build normal). Con `presetId` (selector de demos) → entra a Ejecutar con ese preset ya
 * cargado.
 */
export function LandingLauncher({
  onEnter,
}: {
  onEnter: (presetId?: string) => void
}) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-6xl px-6 lg:px-10">
        {/* Barra de marca */}
        <header className="flex items-center justify-between py-6">
          <div className="flex items-center gap-2.5">
            <NikodymMark className="size-8" />
            <span className="font-display text-xl font-bold tracking-tight text-foreground">
              Nikodym
            </span>
            <span className="mt-1 hidden font-mono text-[0.7rem] uppercase tracking-[0.18em] text-muted-foreground sm:inline">
              RiskLib
            </span>
          </div>
          <div className="flex items-center gap-5">
            <a
              href={DOCS_URL}
              className="font-mono text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              Documentación ↗
            </a>
            <ThemeToggle />
          </div>
        </header>

        {/* §0 — Hero. Asimétrico 7/5: el argumento a la izquierda, la prueba a la derecha. */}
        <main>
          <div className="grid grid-cols-1 items-center gap-10 py-16 lg:grid-cols-12 lg:gap-14 lg:py-24">
            <div className="lg:col-span-7">
              {/* Sin número de versión: un literal aquí se pudre en el siguiente release y la
                  landing termina anunciando una versión que ya no es la de PyPI. La versión viva
                  la dice el lineage del informe, que sale de la corrida. */}
              <p className="font-mono text-xs uppercase tracking-[0.2em] text-eyebrow">
                Motor de riesgo de crédito · Python · Apache-2.0
              </p>
              {/* Las dos líneas del H1 son inseparables: la primera promete, la segunda confiesa. */}
              <h1 className="mt-5 font-display text-[clamp(2.05rem,4.6vw,3.5rem)] font-bold leading-[1.05] tracking-tight text-foreground">
                IFRS 9, CMF y stress
                <br />
                ya los calcula el motor.
                <br />
                <span className="text-muted-foreground">
                  La interfaz ya llega al scorecard y a las provisiones.
                </span>
              </h1>
              <p className="mt-6 max-w-xl text-base leading-relaxed text-muted-foreground">
                El scorecard y las provisiones tienen preset, pantalla e informe; el scorecard es
                además la única superficie bajo garantía SemVer 1.x (las provisiones, la más nueva,
                siguen experimentales). Los otros cuatro ya están implementados y testeados —más de{" "}
                {TESTS_DOMINIOS} tests pasan sobre ellos—, pero hoy se usan escribiendo el config en
                Python a mano, y siguen marcados como experimentales.{" "}
                <span className="text-foreground">
                  No es un roadmap: es el código que ya viene en el paquete.
                </span>
              </p>

              {DEMO_MODE ? (
                <div className="mt-9 space-y-5">
                  <DemoSelector onPick={onEnter} />
                  <ComandoCopiable />
                </div>
              ) : (
                <div className="mt-9 flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => onEnter()}
                    className={cn(
                      "group inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-3",
                      "font-medium text-primary-foreground shadow-card transition-all",
                      "hover:-translate-y-0.5 hover:bg-brand-accent-dark",
                    )}
                  >
                    Construir un scorecard
                    <ArrowRight
                      className="size-4 transition-transform group-hover:translate-x-0.5"
                      aria-hidden="true"
                    />
                  </button>
                  <ComandoCopiable />
                </div>
              )}

              {/* En la demo estática la app NO recalcula: reproduce fixtures. Decirlo, no insinuarlo. */}
              {DEMO_MODE ? (
                <p className="mt-4 max-w-xl text-xs leading-relaxed text-muted-foreground">
                  Esta demo reproduce, paso a paso, la salida verbatim de una corrida real del
                  motor. No recalcula en el navegador ni acepta datasets propios: para eso,{" "}
                  <span className="font-mono text-foreground">pip install nikodym</span>.
                </p>
              ) : null}
            </div>

            <div className="lg:col-span-5">
              <BloqueCodigo />
            </div>
          </div>

          {/* §1 — El motor. Va PRIMERO: es lo que el H1 promete, y el H1 hay que pagarlo aquí. */}
          <Seccion id="§1" titulo="Ya está construido. Lo que falta es la interfaz.">
            <div className="max-w-3xl space-y-4 text-sm leading-relaxed text-muted-foreground">
              <p>
                El estado de cada dominio se lee en dos ejes, y ninguno de los dos es «hecho / no
                hecho».{" "}
                <span className="font-mono text-xs uppercase tracking-[0.1em] text-foreground">
                  Superficie
                </span>
                : tiene <span className="text-foreground">UI</span> (preset, pantalla y capítulo en
                el informe) o se usa desde <span className="text-foreground">Python</span> (hay que
                escribir el config a mano; no hay preset, ni pantalla, ni capítulo en el informe, y
                no existe CLI).{" "}
                <span className="font-mono text-xs uppercase tracking-[0.1em] text-foreground">
                  Garantía
                </span>
                : <span className="text-foreground">estable</span> (contrato congelado bajo SemVer
                1.x) o <span className="text-foreground">experimental</span> (el motor calcula y
                está cubierto por tests, pero la firma puede cambiar dentro de la 1.x; no está
                certificado ni es apto para producción por el solo hecho de existir).
              </p>
              <p>
                Los cuatro dominios sin interfaz son motores deterministas, sin stubs: más de{" "}
                <span className="font-mono text-foreground">{TESTS_DOMINIOS}</span> tests pasan
                sobre ellos, y más de{" "}
                <span className="font-mono text-foreground">{TESTS_SUITE}</span> en la suite
                completa. Corren como pasos del mismo{" "}
                <span className="font-mono text-foreground">Study</span>, con el mismo{" "}
                <span className="font-mono text-foreground">NikodymConfig</span> y el mismo{" "}
                <span className="font-mono text-foreground">config_hash</span> que el scorecard.{" "}
                <span className="text-foreground">
                  Lo que les falta es superficie, no aritmética.
                </span>
              </p>
            </div>

            <ul className="mt-9 divide-y divide-border border-y border-border">
              {DOMINIOS.map((d) => (
                <li key={d.key} className="grid grid-cols-1 gap-3 py-6 sm:grid-cols-12 sm:gap-6">
                  <div className="sm:col-span-4">
                    <p className="font-display font-bold text-foreground">{d.label}</p>
                    <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[0.62rem] uppercase tracking-[0.12em]">
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5",
                          d.superficie === "UI"
                            ? "bg-brand-accent-dark/12 text-brand-accent-dark"
                            : "bg-muted text-muted-foreground",
                        )}
                      >
                        {d.superficie}
                      </span>
                      <span
                        className={cn(
                          d.garantia === "estable" ? "text-eyebrow" : "text-muted-foreground",
                        )}
                      >
                        {d.garantia}
                      </span>
                    </p>
                    <code className="mt-2 block font-mono text-xs text-muted-foreground">
                      import {d.modulo}
                    </code>
                  </div>
                  <p className="text-sm leading-relaxed text-muted-foreground sm:col-span-8">
                    {d.tagline}
                  </p>
                </li>
              ))}
            </ul>

            {/* Las salvedades no van en letra chica: el motor las publica en cada fila que emite. */}
            <div className="mt-8 rounded-xl border border-border bg-card p-5">
              <p className="font-mono text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
                Lo que el motor declara de sí mismo
              </p>
              <dl className="mt-4 space-y-3">
                {SALVEDADES.map((s) => (
                  <div key={s.clave} className="grid grid-cols-1 gap-1 sm:grid-cols-12 sm:gap-4">
                    <dt className="font-mono text-xs text-foreground sm:col-span-3">{s.clave}</dt>
                    <dd className="text-sm leading-relaxed text-muted-foreground sm:col-span-9">
                      {s.texto}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          </Seccion>

          {/* §2 — Cómo funciona. El get-started: el pipeline completo en una tabla legible. */}
          <Seccion id="§2" titulo="Cómo funciona el scorecard, paso a paso">
            <ol>
              {PIPELINE.map((p) => (
                <li
                  key={p.n}
                  className={cn(
                    "grid grid-cols-1 gap-1 border-b border-border py-4 transition-colors",
                    "hover:bg-card sm:grid-cols-12 sm:items-baseline sm:gap-4",
                  )}
                >
                  <span className="font-mono text-xs text-muted-foreground sm:col-span-1">
                    {p.n}
                  </span>
                  <span className="font-display font-bold text-foreground sm:col-span-2">
                    {p.paso}
                  </span>
                  <span className="text-sm leading-relaxed text-muted-foreground sm:col-span-6">
                    {p.hace}
                  </span>
                  <span className="font-mono text-xs text-eyebrow sm:col-span-3 sm:text-right">
                    {p.dato}
                  </span>
                </li>
              ))}
            </ol>
            <p className="mt-5 text-sm text-muted-foreground">
              La columna de la derecha es la corrida de demostración, no un ejemplo inventado.
              Puedes ejecutarla tal cual, sin configurar nada.
            </p>
          </Seccion>

          {/* §3 — La evidencia. Producto real: la curva y las métricas de una corrida de verdad. */}
          <Seccion id="§3" titulo="La evidencia">
            <div className="grid grid-cols-1 gap-10 lg:grid-cols-12 lg:gap-12">
              <div className="lg:col-span-6">
                <CurvaGains />
              </div>
              <div className="lg:col-span-6">
                <dl className="border-t border-border">
                  {METRICAS.map((m) => (
                    <div
                      key={m.clave}
                      className="flex items-baseline gap-4 border-b border-border py-3.5"
                    >
                      <dt className="w-12 shrink-0 font-mono text-xs uppercase tracking-[0.12em] text-muted-foreground">
                        {m.clave}
                      </dt>
                      <dd className="font-mono text-lg text-foreground">{m.valor}</dd>
                      <dd className="ml-auto font-mono text-[0.68rem] text-muted-foreground">
                        {m.nota}
                      </dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-6 text-sm leading-relaxed text-muted-foreground">
                  Estos números salen de una corrida real sobre el dataset sintético de la demo.
                  Los tuyos serán otros: el punto no es la métrica, es que se calcule sola, quede
                  trazada al <span className="font-mono text-foreground">data_hash</span> y se
                  pueda reproducir en otra máquina.
                </p>
                <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
                  El motor también levanta la bandera cuando algo no cuadra: el PSI vigila la
                  estabilidad entre particiones y la calibración se contrasta contra la tasa
                  observada.
                </p>
              </div>
            </div>
          </Seccion>

          {/* §4 — El entregable. El diferenciador: no entregas un log, entregas un informe. */}
          <Seccion id="§4" titulo="El entregable">
            <div className="grid grid-cols-1 gap-10 lg:grid-cols-12 lg:gap-12">
              <div className="lg:col-span-5">
                <p className="font-display text-2xl font-bold leading-snug text-foreground">
                  No entregas un log.
                  <br />
                  Entregas un informe.
                </p>
                <p className="mt-5 text-sm leading-relaxed text-muted-foreground">
                  El motor redacta la metodología y los resultados con los parámetros que
                  realmente usó, y te deja marcados los capítulos que solo puedes escribir tú:
                  el contexto de tu cartera y la conclusión que vas a firmar.
                </p>
                <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
                  Sale en HTML y PDF, y también como base editable para que armes tu propia
                  documentación encima.
                </p>
              </div>

              <div className="lg:col-span-7">
                <div className="rounded-xl border border-border bg-card p-6 shadow-card">
                  <ol className="space-y-px">
                    {CAPITULOS.map((c) => (
                      <li
                        key={c.n}
                        className="flex items-baseline gap-4 border-b border-border/60 py-3 last:border-0"
                      >
                        <span className="w-4 shrink-0 font-mono text-xs text-muted-foreground">
                          {c.n}
                        </span>
                        <span className="flex-1 font-display font-bold text-foreground">
                          {c.titulo}
                        </span>
                        <span
                          className={cn(
                            "font-mono text-[0.62rem] uppercase tracking-[0.12em]",
                            c.tipo === "generado"
                              ? "text-eyebrow"
                              : "text-muted-foreground",
                          )}
                        >
                          {c.tipo === "generado" ? "lo escribe el motor" : "lo escribes tú"}
                        </span>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>
            </div>
          </Seccion>

          {/* §5 — Quién lo construye. Va al FINAL, nunca en la barra de marca: la tesis de esta
              página es evidencia primero, y un enlace de venta antes de §3 convertiría una landing
              de producto en una de agencia. Aquí el visitante ya vio la evidencia y el entregable. */}
          <Seccion id="§5" titulo="Quién lo construye">
            <div className="lg:max-w-2xl">
              <p className="text-base leading-relaxed text-muted-foreground">
                Nikodym RiskLib lo construye{" "}
                <span className="text-foreground">Nexo Labs</span>, una consultora chilena de riesgo
                y analítica de datos. El motor es Apache-2.0 y no tiene edición comercial ni
                funciones reservadas: está publicado para que puedas leer el código antes de hablar
                con nosotros.
              </p>
              {/* OJO: no decir que la librería "no calibra" — sí calibra, y §2 presume de ello.
                  Lo que el motor NO hace es ELEGIR el ancla (TTC vs PIT) ni de dónde sale la tasa
                  central: eso es `AnchorKind`/`AnchorSource` en calibration/config.py, y lo decide
                  el modelador. Fabricar un hueco que el motor sí cubre sería la mentira exacta que
                  el README promete no decir. */}
              <p className="mt-4 text-base leading-relaxed text-muted-foreground">
                Una librería calcula; no decide. El binning, la calibración y las métricas los corre
                el motor —pero a qué tasa central anclas (TTC o PIT), dónde pones el corte y qué
                supuestos sostienes ante Validación o ante la CMF sigue siendo juicio de modelo.{" "}
                <span className="text-foreground">Si ese es el problema, hay un caso que proponer.</span>
              </p>

              <div className="mt-9">
                <a
                  href={CASO_URL}
                  target="_blank"
                  rel="noreferrer"
                  className={cn(
                    "group inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-3",
                    "font-medium text-primary-foreground shadow-card transition-all",
                    "hover:-translate-y-0.5 hover:bg-brand-accent-dark",
                  )}
                >
                  Proponer un caso
                  <ArrowUpRight
                    className="size-4 transition-transform group-hover:translate-x-0.5"
                    aria-hidden="true"
                  />
                </a>
              </div>

              {/* Copy ya publicado por la consultora (no es una promesa nueva de esta página). */}
              <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
                Cada caso se evalúa antes de aceptarse. Si no hay caso, también te lo decimos, en
                menos de 48 horas hábiles. Cero datos sensibles para partir.
              </p>
            </div>
          </Seccion>
        </main>

        <footer className="flex flex-col gap-4 border-t border-border py-8 sm:flex-row sm:items-center sm:justify-between">
          {/* `flex-wrap`: a 390px los dos hijos exceden la fila por ~5px y, sin envolver, cada uno
              se parte por dentro ("APACHE-" / "2.0"). Que baje el enlace entero, no las palabras. */}
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
            <span className="font-mono text-[0.7rem] uppercase tracking-[0.14em] text-muted-foreground">
              Nikodym RiskLib · Apache-2.0
            </span>
            <a
              href={CASO_URL_FOOTER}
              target="_blank"
              rel="noreferrer"
              className="whitespace-nowrap font-mono text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              Nexo Labs ↗
            </a>
          </div>
          <ComandoCopiable className="sm:py-2" />
        </footer>
      </div>
    </div>
  )
}
