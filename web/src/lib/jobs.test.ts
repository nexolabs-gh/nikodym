/**
 * Tests de la navegación por TRABAJO (D-JOB-1/9/16/17).
 *
 * El runner corre en entorno `node` (sin DOM), así que aquí vive la lógica pura —filtrar secciones,
 * sembrar el esqueleto, decidir qué trabajo corresponde a un config— y la verificación de que el
 * sidebar de verdad se recorta se hace **en la pantalla**, con Playwright. Es la misma limitación
 * declarada del paquete D, y por eso el guardrail estático del final: vitest no puede cazar
 * renderizando que alguien vuelva a mapear el catálogo entero.
 */

import { describe, expect, it } from "vitest"

import appSource from "@/App.tsx?raw"
import configTabSource from "@/components/ConfigTab.tsx?raw"
import { configEditadoRespectoDelPreset } from "@/lib/bootstrap"
import {
  FIXTURE_JOBS,
  decisionStatuses,
  jobForConfig,
  jobSkeleton,
  sectionsOfJob,
  type Job,
} from "@/lib/jobs"
import { CONFIG_SECTIONS } from "@/lib/schema"

const JOBS = FIXTURE_JOBS.jobs
const porId = (id: string): Job => {
  const job = JOBS.find((j) => j.id === id)
  if (!job) throw new Error(`el fixture no trae el trabajo ${id}`)
  return job
}

/** Catálogo de defaults efectivos mínimo, con la forma que publica `GET /api/schema`. */
const CATALOGO = {
  version: 1,
  sections: {
    binning: { max_n_bins: { has_default: true, value: 8 } },
    data: { schema: { strict: { has_default: true, value: false } } },
    report: { output_dir: { has_default: true, value: "reports" } },
  },
  $defs: {},
} as never

describe("el fixture del catálogo es utilizable por sí solo", () => {
  it("trae trabajos, con al menos uno disponible y uno no disponible", () => {
    // Ancla anti-tautología: con el fixture vacío, todo lo de abajo pasaría por vacuidad y
    // «ninguna sección de más en el sidebar» se leería igual que «el filtro funciona».
    expect(JOBS.length).toBeGreaterThanOrEqual(8)
    expect(new Set(JOBS.map((j) => j.status))).toEqual(
      new Set(["available", "unavailable"]),
    )
  })

  it("cada sección que declara un trabajo existe en el formulario", () => {
    // Espejo en el front del gate bidireccional de `test_jobs_catalogo.py`: aquí sólo puede
    // desincronizarse el FIXTURE, y su drift contra el backend lo vigila ese mismo gate.
    const conocidas = new Set(CONFIG_SECTIONS.map((s) => s.key))
    const inexistentes = JOBS.flatMap((j) =>
      j.sections.filter((s) => !conocidas.has(s)).map((s) => `${j.id}:${s}`),
    )
    expect(inexistentes).toEqual([])
  })
})

describe("sectionsOfJob (el trabajo decide qué secciones existen · D-JOB-1)", () => {
  it("un trabajo de scoring NO puede pintar IFRS 9, survival ni CMF", () => {
    const claves = sectionsOfJob(porId("scorecard_pd")).map((s) => s.key)
    expect(claves).not.toContain("provisioning_ifrs9")
    expect(claves).not.toContain("survival")
    expect(claves).not.toContain("provisioning_cmf")
    expect(claves).toContain("binning")
  })

  it("un trabajo de provisión interna NO puede pintar binning ni el modelo", () => {
    const claves = sectionsOfJob(porId("provision_interna")).map((s) => s.key)
    expect(claves).toEqual(["data", "provisioning_internal", "report"])
  })

  it("conserva el orden CANÓNICO del pipeline, no el del catálogo", () => {
    // Si tomara el orden de `job.sections`, el sidebar dependería de cómo se escribió el catálogo
    // y dos trabajos podrían pintar las mismas secciones en orden distinto.
    const orden = CONFIG_SECTIONS.map((s) => s.key)
    for (const job of JOBS) {
      const claves = sectionsOfJob(job).map((s) => s.key)
      expect(claves).toEqual(orden.filter((k) => claves.includes(k)))
    }
  })

  it("sin trabajo elegido se ven todas: es el config del usuario, no el nuestro", () => {
    expect(sectionsOfJob(null)).toEqual(CONFIG_SECTIONS)
  })
})

describe("jobSkeleton (elegir un trabajo siembra SU esqueleto · D-JOB-16)", () => {
  const vacio = { name: "nikodym-study", binning: null, data: null, report: null, survival: null }

  it("activa las secciones del trabajo con su proyección canónica y deja el resto apagado", () => {
    const skeleton = jobSkeleton(vacio, porId("scorecard_pd"), CATALOGO)

    expect(skeleton.binning).toEqual({ max_n_bins: 8 })
    expect(skeleton.data).toEqual({ schema: { strict: false } })
    expect(skeleton.report).toEqual({ output_dir: "reports" })
    // `survival` no es de este trabajo: queda apagada, y el motor no la ejecuta.
    expect(skeleton.survival).toBeNull()
  })

  it("NO trae dataset: el primer gesto sigue siendo traer el tuyo", () => {
    const skeleton = jobSkeleton(vacio, porId("scorecard_pd"), CATALOGO)
    expect(Object.keys(skeleton)).not.toContain("dataset_id")
  })

  it("no muta el config que recibe", () => {
    const antes = structuredClone(vacio)
    jobSkeleton(vacio, porId("scorecard_pd"), CATALOGO)
    expect(vacio).toEqual(antes)
  })

  it("sin catálogo de defaults deja las secciones como estaban, en vez de sembrarlas a medias", () => {
    // Sembrar con `{}` produciría una sección incompleta que el motor rechaza, y un config
    // inválido nada más entrar sería peor que uno apagado.
    const skeleton = jobSkeleton(vacio, porId("scorecard_pd"), undefined)
    expect(skeleton).toEqual(vacio)
  })
})

describe("jobForConfig (un YAML selecciona su trabajo · D-JOB-17)", () => {
  it("un config de sólo survival cae en el trabajo MÁS PEQUEÑO que lo contiene", () => {
    // «PD lifetime» y «Provisiones IFRS 9» contienen ambos {data, survival, report}; el correcto
    // es el que no añade pantallas que el config no usa.
    const job = jobForConfig(JOBS, { data: {}, survival: {}, report: {} })
    expect(job?.id).toBe("pd_lifetime")
  })

  it("un config de scorecard + provisión interna cae en el trabajo compuesto", () => {
    const job = jobForConfig(JOBS, {
      data: {},
      binning: {},
      selection: {},
      model: {},
      scorecard: {},
      calibration: {},
      performance: {},
      stability: {},
      provisioning_internal: {},
      report: {},
    })
    expect(job?.id).toBe("pd_y_lgd")
  })

  it("un config que no calza con ningún trabajo deja la sesión SIN trabajo (formulario completo)", () => {
    // Es la regla que cierra el caso sin un parche en la vista: esconderle al usuario parte de lo
    // que él mismo trajo sería la mentira contraria a la que D-JOB-17 evita.
    const job = jobForConfig(JOBS, {
      data: {},
      binning: {},
      provisioning_cmf: {},
      survival: {},
      provisioning_ifrs9: {},
      report: {},
    })
    expect(job).toBeNull()
    expect(sectionsOfJob(job)).toEqual(CONFIG_SECTIONS)
  })

  it("un config vacío no selecciona trabajo: sin señal no se adivina", () => {
    // D-JOB-1 veta derivar el trabajo de las secciones no nulas como mecanismo general —con
    // «empezar de cero» dejaría el sidebar vacío—. Cargar un YAML es la excepción porque hay señal.
    expect(jobForConfig(JOBS, { data: null, binning: null })).toBeNull()
    expect(jobForConfig(JOBS, {})).toBeNull()
  })

  it("una sección apagada no cuenta como activa", () => {
    const job = jobForConfig(JOBS, {
      data: {},
      survival: {},
      report: {},
      provisioning_ifrs9: null,
    })
    expect(job?.id).toBe("pd_lifetime")
  })
})

describe("D-JOB-9: el trabajo es navegación, no identidad", () => {
  it("dos trabajos que llevan al mismo config producen el mismo config", () => {
    // El `config_hash` lo calcula el backend sobre el config; si el trabajo no aparece en el
    // config, no puede aparecer en el hash. Lo que este test cierra es que el esqueleto no
    // introduzca una marca del trabajo por la puerta de atrás.
    const base = { data: null, binning: null, report: null, survival: null }
    const a = jobSkeleton(base, porId("pd_lifetime"), CATALOGO)
    const b = jobSkeleton(base, porId("provisiones_ifrs9"), CATALOGO)
    for (const skeleton of [a, b]) {
      expect(Object.keys(skeleton).some((k) => /job|trabajo/i.test(k))).toBe(false)
    }
    // Y el mismo trabajo sobre el mismo config vacío es determinista.
    expect(jobSkeleton(base, porId("pd_lifetime"), CATALOGO)).toEqual(a)
  })
})

describe("el trabajo elegido se declara en el estado de la sesión", () => {
  it("`App.tsx` marca el seed como `job`, no lo deja en `empty`", () => {
    // Verificado en la pantalla antes de escribir este guardrail: sin esto, el aviso de
    // Configuración seguía diciendo «sesión nueva, sin configuración» sobre un formulario que YA
    // traía las secciones sembradas — el copy contradecía lo que el usuario tenía delante.
    expect(appSource).toMatch(/setSeed\(\{\s*kind:\s*"job"/)
  })

  it("`job` no cuenta como config editado: no hay preset contra el cual comparar", () => {
    expect(
      configEditadoRespectoDelPreset(
        { kind: "job", jobId: "scorecard_pd", label: "Scorecard" },
        { binning: {} },
      ),
    ).toBe(false)
  })
})

describe("guardrail: el sidebar no puede volver a mapear el catálogo entero", () => {
  it("`App.tsx` construye la navegación desde las secciones del trabajo", () => {
    // El defecto que D-JOB-1 corrige era literalmente `CONFIG_SECTIONS.map(...)` dentro del NAV.
    // Vitest corre sin DOM y no puede cazarlo renderizando, así que se vigila el fuente — mismo
    // motivo y misma forma que el guardrail de propagación del catálogo del paquete D.
    expect(appSource).toMatch(/navItems\(configSections\)/)
    expect(appSource).toMatch(/sectionsOfJob\(job\)/)
    expect(appSource).not.toMatch(/children:\s*CONFIG_SECTIONS\.map/)
  })
})

describe("decisiones obligatorias del trabajo (D-OBL-6)", () => {
  it("el catálogo bundleado las trae, y son las medidas", () => {
    // Si el fixture se quedara viejo, la tarjeta desaparecería sin que ningún test lo notara.
    expect(porId("scorecard_pd").required_decisions.map((d) => d.path)).toEqual([
      "data.target.bad_rule",
      "data.partition.strategy",
    ])
    // Los dos trabajos con survival preguntan cuatro cosas, no dos.
    expect(porId("pd_lifetime").required_decisions.map((d) => d.path)).toEqual([
      "data.target.bad_rule",
      "data.partition.strategy",
      "survival.input.duration_col",
      "survival.input.event_col",
    ])
  })

  it("una pregunta se lee como pregunta y nunca enseña el path (D-OBL-9)", () => {
    for (const job of JOBS) {
      for (const decision of job.required_decisions) {
        expect(decision.question).toMatch(/\?$/)
        expect(decision.question).not.toContain(decision.path)
        expect(decision.help).not.toContain(decision.path)
        expect(decision.help.length).toBeGreaterThan(40)
      }
    }
  })

  it("responder se decide por PRESENCIA de la clave, no por truthiness", () => {
    const job = porId("scorecard_pd")
    // Sin config no se afirma nada.
    expect(decisionStatuses(job, null)).toEqual([])
    expect(decisionStatuses(null, {})).toEqual([])

    // Config vacío: las dos pendientes.
    expect(decisionStatuses(job, {}).map((d) => d.answered)).toEqual([false, false])

    // Una respondida con un valor FALSY explícito sigue siendo una respuesta del usuario: es el
    // mismo criterio de D-FX-7, y usar truthiness aquí volvería a confundir «vacío» con «ausente».
    const conFalsy = {
      data: { target: { bad_rule: null }, partition: { strategy: "" } },
    }
    expect(decisionStatuses(job, conFalsy).map((d) => d.answered)).toEqual([true, true])

    // Y una rama a medias no cuenta como respondida.
    expect(
      decisionStatuses(job, { data: { target: {} } }).map((d) => d.answered),
    ).toEqual([false, false])
  })

  it("un trabajo sin decisiones no fabrica ninguna", () => {
    const sinDecisiones: Job = { ...porId("scorecard_pd"), required_decisions: [] }
    expect(decisionStatuses(sinDecisiones, {})).toEqual([])
  })
})

describe("guardrail: las decisiones se pintan al principio de Configuración (D-OBL-8)", () => {
  it("`ConfigTab` monta la tarjeta y la acota a su sección", () => {
    // Vitest corre sin DOM y no puede comprobar el ORDEN renderizando, así que se vigila el fuente:
    // misma forma y mismo motivo que el guardrail del sidebar de aquí arriba.
    expect(configTabSource).toMatch(/<RequiredDecisions/)
    expect(configTabSource).toMatch(/decisions=\{decisionStatuses\(job, /)
    expect(configTabSource).toMatch(/section=\{section\}/)
    // Y va ANTES del formulario. Se mide DENTRO del return de `ConfigTab`: el archivo tiene un
    // helper que renderiza grupos y monta su propio `<Accordion>` mucho antes, así que buscar el
    // primer acordeón del fichero comparaba contra otro componente y daba un rojo falso.
    const cuerpo = configTabSource.slice(
      configTabSource.indexOf("export function ConfigTab"),
    )
    expect(cuerpo.indexOf("<RequiredDecisions")).toBeGreaterThan(-1)
    expect(cuerpo.indexOf("<RequiredDecisions")).toBeLessThan(cuerpo.indexOf("<PreflightNotice"))
    expect(cuerpo.indexOf("<RequiredDecisions")).toBeLessThan(cuerpo.indexOf("<ConfigSectionForm"))
  })
})
