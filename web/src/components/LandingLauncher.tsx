import { useState } from "react"
import { ArrowRight, Check, Copy } from "lucide-react"

import { NikodymMark } from "@/components/NikodymMark"
import { ThemeToggle } from "@/components/ThemeToggle"
import {
  CAPITULOS,
  CODIGO,
  DOMINIOS,
  GAINS_HOLDOUT,
  METRICAS,
  PIPELINE,
} from "@/components/landing-evidence"
import { cn } from "@/lib/utils"

/**
 * Landing / launcher de nivel-0. Rediseño 2026-07-12.
 *
 * Voz: el documento técnico que el propio motor produce (secciones §, grid estricto, cifras en
 * mono, reglas finas). NO es una landing SaaS: quien llega es un analista de riesgo evaluando si
 * esto le sirve para un entregable que va a Validación, y a ese público lo convence la evidencia,
 * no el marketing.
 *
 * Regla dura: cada cifra de esta pantalla sale de una corrida REAL (ver `landing-evidence.ts`).
 * Cero lógica de dominio: solo navegación.
 */

const DOCS_URL = "https://docs.nikodym.cl"
const PYPI_CMD = "pip install nikodym"

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

/** Pantalla de nivel-0: `onEnter` entra al workspace (flujo F1 del scorecard). */
export function LandingLauncher({ onEnter }: { onEnter: () => void }) {
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
              <p className="font-mono text-xs uppercase tracking-[0.2em] text-eyebrow">
                Motor de riesgo de crédito · Python · Apache-2.0
              </p>
              <h1 className="mt-5 font-display text-[clamp(2.25rem,5vw,3.75rem)] font-bold leading-[1.05] tracking-tight text-foreground">
                Del dato crudo al scorecard
                <br />
                que Validación aprueba.
              </h1>
              <p className="mt-6 max-w-xl text-base leading-relaxed text-muted-foreground">
                Binning WoE, selección, modelo PD, calibración y provisiones. Con el informe
                que lo defiende: mismo <span className="font-mono text-foreground">config_hash</span>,
                mismo resultado, siempre.
              </p>

              <div className="mt-9 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={onEnter}
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
            </div>

            <div className="lg:col-span-5">
              <BloqueCodigo />
            </div>
          </div>

          {/* §1 — Cómo funciona. El get-started: el pipeline completo en una tabla legible. */}
          <Seccion id="§1" titulo="Cómo funciona">
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

          {/* §2 — La evidencia. Producto real: la curva y las métricas de una corrida de verdad. */}
          <Seccion id="§2" titulo="La evidencia">
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

          {/* §3 — El entregable. El diferenciador: no entregas un log, entregas un informe. */}
          <Seccion id="§3" titulo="El entregable">
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

          {/* §4 — Los dominios. Honestidad: el motor los calcula HOY, desde Python. */}
          <Seccion id="§4" titulo="Los otros cinco dominios">
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              El scorecard es el único con interfaz gráfica. Los demás ya están calculados por el
              motor y se usan hoy desde Python: son módulos reales, no promesas. Siguen marcados
              como experimentales, así que su API puede cambiar dentro de la 1.x.
            </p>

            <ul className="mt-8 divide-y divide-border border-y border-border">
              {DOMINIOS.map((d) => (
                <li
                  key={d.key}
                  className="grid grid-cols-1 gap-2 py-5 sm:grid-cols-12 sm:items-baseline sm:gap-4"
                >
                  <span className="font-display font-bold text-foreground sm:col-span-3">
                    {d.label}
                  </span>
                  <span className="text-sm leading-relaxed text-muted-foreground sm:col-span-5">
                    {d.tagline}
                  </span>
                  <code className="font-mono text-xs text-muted-foreground sm:col-span-4 sm:text-right">
                    import {d.modulo}
                  </code>
                </li>
              ))}
            </ul>
          </Seccion>
        </main>

        <footer className="flex flex-col gap-4 border-t border-border py-8 sm:flex-row sm:items-center sm:justify-between">
          <span className="font-mono text-[0.7rem] uppercase tracking-[0.14em] text-muted-foreground">
            Nikodym RiskLib · Apache-2.0
          </span>
          <ComandoCopiable className="sm:py-2" />
        </footer>
      </div>
    </div>
  )
}
