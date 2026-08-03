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
  jobSwitchForConfig,
  jobSwitchNotice,
  sectionsOfJob,
  type Job,
} from "@/lib/jobs"
import { CONFIG_SECTIONS, FIXTURE_SCHEMA } from "@/lib/schema"
import type { ValidationState } from "@/lib/validation"

/** Sin veredicto del motor: manda el criterio de huecos, que es el de siempre (D-RES-4). */
const SIN_VEREDICTO: ValidationState = { kind: "idle" }

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

  it("un trabajo NO disponible sí puede salir elegido, y es lo correcto (medido)", () => {
    // Con `{data, report}` a secas, el más pequeño que los contiene es «Stress testing», que la
    // landing declara no disponible (D-JOB-6). Descartar los no disponibles aquí PARECE la mejora
    // obvia y empeora el resultado: los candidatos disponibles más pequeños tienen tres secciones,
    // así que la sesión pasaría a un trabajo que pinta una sección que el config NO trae. El
    // `status` gobierna si un trabajo se puede INICIAR desde la landing, no cómo se describe un
    // config que el usuario ya tiene. Este test existe para que ese "arreglo" no se cuele.
    const job = jobForConfig(JOBS, { data: {}, report: {} })
    expect(job?.id).toBe("stress_testing")
    expect(sectionsOfJob(job).map((s) => s.key)).toEqual(["data", "report"])
  })
})

describe("jobSwitchForConfig (el config traído de fuera contra el trabajo activo · D-JOB-17)", () => {
  it("dice qué trabajo dejar Y si eso cambia lo que el usuario tenía", () => {
    const cambio = jobSwitchForConfig(
      JOBS,
      { data: {}, survival: {}, report: {} },
      porId("scorecard_pd"),
    )
    expect(cambio).toEqual({ job: porId("pd_lifetime"), cambia: true })
  })

  it("compara por `id`, no por identidad de objeto", () => {
    // El catálogo se vuelve a pedir en cada carga, así que el MISMO trabajo llega como un objeto
    // distinto; comparar referencias diría «cambió» siempre y el aviso saltaría en cada YAML.
    const clon = structuredClone(porId("pd_lifetime"))
    const cambio = jobSwitchForConfig(
      JOBS,
      { data: {}, survival: {}, report: {} },
      clon,
    )
    expect(clon).not.toBe(porId("pd_lifetime"))
    expect(cambio.cambia).toBe(false)
  })

  it("sin trabajo activo y sin trabajo elegible no hay cambio que anunciar", () => {
    expect(jobSwitchForConfig(JOBS, {}, null)).toEqual({ job: null, cambia: false })
  })

  it("perder el trabajo TAMBIÉN es un cambio: el sidebar pasa a mostrarlo todo", () => {
    const cambio = jobSwitchForConfig(JOBS, {}, porId("scorecard_pd"))
    expect(cambio).toEqual({ job: null, cambia: true })
    expect(sectionsOfJob(cambio.job)).toEqual(CONFIG_SECTIONS)
  })
})

describe("jobSwitchNotice (qué se le dice al usuario · D-JOB-17)", () => {
  it("sin cambio de trabajo no hay aviso", () => {
    // Un aviso que se dispara de más se aprende a ignorar.
    expect(jobSwitchNotice({ job: porId("scorecard_pd"), cambia: false }, "archivo")).toBeNull()
    expect(jobSwitchNotice({ job: null, cambia: false }, "ejemplo")).toBeNull()
  })

  it("el aviso explica qué pasó con el menú, no sólo qué trabajo es", () => {
    const aviso = jobSwitchNotice({ job: porId("pd_lifetime"), cambia: true }, "archivo")
    expect(aviso).toContain("PD lifetime")
    expect(aviso).toMatch(/menú|secciones/)
  })

  it("nombra el trabajo por su etiqueta de negocio, NUNCA por su id", () => {
    // El `id` es coordenada interna, como el `path` de una decisión obligatoria (D-JOB-14).
    for (const origen of ["archivo", "ejemplo"] as const) {
      const aviso = jobSwitchNotice(
        { job: porId("provisiones_ifrs9"), cambia: true },
        origen,
      )
      expect(aviso).toContain("Provisiones IFRS 9 / ECL")
      expect(aviso).not.toContain("provisiones_ifrs9")
    }
  })

  it("las dos puertas nombran lo que el usuario acaba de traer, y sólo se diferencian en eso", () => {
    // Es la razón de que el texto viva en UN sitio: llamarle «archivo» al ejemplo (o al revés)
    // sería un aviso que describe un gesto que el usuario no hizo. El resto de la frase es la
    // misma, y duplicarla habría dejado dos copys que se separan en silencio.
    const cambio = { job: porId("pd_lifetime"), cambia: true }
    const archivo = jobSwitchNotice(cambio, "archivo") ?? ""
    const ejemplo = jobSwitchNotice(cambio, "ejemplo") ?? ""
    expect(archivo).toMatch(/^Este archivo /)
    expect(ejemplo).toMatch(/^Este ejemplo /)
    expect(archivo.replace(/^Este archivo /, "")).toBe(
      ejemplo.replace(/^Este ejemplo /, ""),
    )
  })

  it("sin trabajo elegible dice que se ven todas las secciones (y no inventa un trabajo)", () => {
    const aviso = jobSwitchNotice({ job: null, cambia: true }, "ejemplo")
    expect(aviso).toContain("todas las secciones")
    expect(aviso).toContain("sin trabajo")
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
    expect(decisionStatuses(job, null, SIN_VEREDICTO)).toEqual([])
    expect(decisionStatuses(null, {}, SIN_VEREDICTO)).toEqual([])

    // Config vacío: las dos pendientes.
    expect(decisionStatuses(job, {}, SIN_VEREDICTO).map((d) => d.answered)).toEqual([false, false])

    // Una respondida con un valor FALSY explícito sigue siendo una respuesta del usuario: es el
    // mismo criterio de D-FX-7, y usar truthiness aquí volvería a confundir «vacío» con «ausente».
    const conFalsy = {
      data: { target: { bad_rule: null }, partition: { strategy: "" } },
    }
    expect(decisionStatuses(job, conFalsy, SIN_VEREDICTO).map((d) => d.answered)).toEqual([true, true])

    // Y una rama a medias no cuenta como respondida.
    expect(
      decisionStatuses(job, { data: { target: {} } }, SIN_VEREDICTO).map((d) => d.answered),
    ).toEqual([false, false])
  })

  it("un trabajo sin decisiones no fabrica ninguna", () => {
    const sinDecisiones: Job = { ...porId("scorecard_pd"), required_decisions: [] }
    expect(decisionStatuses(sinDecisiones, {}, SIN_VEREDICTO)).toEqual([])
  })
})

describe("formas de respuesta de una decisión (D-COL-6/8)", () => {
  const scorecard = porId("scorecard_pd")
  const formaDe = (path: string, id: string) => {
    const forma = scorecard.required_decisions
      .find((d) => d.path === path)!
      .answer_forms.find((f) => f.id === id)
    expect(forma, `no existe la forma ${id} de ${path}`).toBeDefined()
    return forma!
  }

  it("el catálogo bundleado trae las formas, y ninguna se enseña por su id", () => {
    // Si el fixture se quedara viejo el selector desaparecería sin que nada lo notara — es el
    // mismo motivo por el que las decisiones se anclan aquí arriba.
    //
    // Que el label no SEA el id es la trampa de `Select.Value` escrita como aserción: ya se pagó
    // dos veces pintando el valor crudo (`__por_orden__`, `f4-ifrs9-retail`) donde debía leerse su
    // etiqueta. No basta con que exista una etiqueta: tiene que ser distinta del identificador.
    for (const job of JOBS) {
      for (const decision of job.required_decisions) {
        for (const forma of decision.answer_forms) {
          expect(forma.label).not.toBe(forma.id)
          expect(forma.label).toMatch(/ /)
          expect(forma.help.length).toBeGreaterThan(40)
        }
      }
    }
    expect(
      scorecard.required_decisions
        .find((d) => d.path === "data.partition.strategy")!
        .answer_forms.map((f) => f.id),
    ).toEqual(["temporal", "cohort", "columna", "random"])
    expect(
      scorecard.required_decisions
        .find((d) => d.path === "data.target.bad_rule")!
        .answer_forms.map((f) => f.id),
    ).toEqual(["condiciones", "columna_marcada"])
  })

  it("🔴 elegir una forma NO da la decisión por contestada mientras queden sus huecos", () => {
    // Es el corazón de D-COL-8. Sin el tercer estado, escribir la plantilla pondría el tilde de
    // «respondida» sobre una regla sin columna ni valor, y el error saldría mucho después.
    const conPlantilla = {
      data: { target: { bad_rule: formaDe("data.target.bad_rule", "columna_marcada").template } },
    }
    const [badRule] = decisionStatuses(scorecard, conPlantilla, SIN_VEREDICTO)
    expect(badRule.answered).toBe(false)
    expect(badRule.inProgress).toBe(true)
  })

  it("rellenados los huecos, queda contestada", () => {
    const conDatos = {
      data: {
        target: { bad_rule: { all_of: [{ col: "bad_flag", op: "==", value: 1 }], any_of: [] } },
      },
    }
    const [badRule] = decisionStatuses(scorecard, conDatos, SIN_VEREDICTO)
    expect(badRule.answered).toBe(true)
    expect(badRule.inProgress).toBe(false)
  })

  it("una forma sin huecos queda contestada de un clic", () => {
    // `random` no deja ninguno: sus tres fracciones son defaults del motor, no criterio de nadie.
    const alAzar = {
      data: { partition: { strategy: formaDe("data.partition.strategy", "random").template } },
    }
    const particion = decisionStatuses(scorecard, alAzar, SIN_VEREDICTO)[1]
    expect(particion.answered).toBe(true)
    expect(particion.inProgress).toBe(false)
  })

  it("los huecos de OTRA forma no cuentan: no hay que adivinar cuál eligió el usuario", () => {
    // Una partición aleatoria no tiene `date_col` ni `cohort_col`; esos slots existen en el
    // catálogo pero no en el valor, y comprobarlos por ausencia los daría por vacíos — dejando la
    // decisión eternamente «a medias» por huecos de una forma que nadie eligió.
    const porCohorte = {
      data: {
        partition: {
          strategy: { type: "cohort", cohort_col: "cohorte", oot_cohorts: ["2024Q2"] },
        },
      },
    }
    expect(decisionStatuses(scorecard, porCohorte, SIN_VEREDICTO)[1].answered).toBe(true)
  })

  it("🔴 un hueco que la forma NO exige no deja la decisión colgada", () => {
    // Los dos casos que la revisión adversarial midió, y que la primera versión de esto declaraba
    // incompletos sobre configs que el motor ACEPTA. Un falso «te falta un dato» es tan dañino
    // como el falso tilde verde: manda a buscar un dato que nadie pidió.
    //
    // (a) `isna` pregunta por la AUSENCIA de dato: no lleva valor con qué comparar.
    const porAusencia = {
      data: { target: { bad_rule: { all_of: [{ col: "marca", op: "isna", value: null }] } } },
    }
    const [reglaIsna] = decisionStatuses(scorecard, porAusencia, SIN_VEREDICTO)
    expect([reglaIsna.answered, reglaIsna.inProgress]).toEqual([true, false])

    // (b) D-COL-4: las particiones exigidas son EXACTAMENTE las que el usuario mapeó. Una
    // institución que sólo separa validación tiene una respuesta completa.
    const soloHoldout = {
      data: {
        partition: {
          strategy: { type: "columna", partition_col: "m", desarrollo: [], holdout: ["V"], oot: [] },
        },
      },
    }
    expect(decisionStatuses(scorecard, soloHoldout, SIN_VEREDICTO)[1].answered).toBe(true)
  })

  it("pero sin NINGUNA muestra mapeada sigue incompleta", () => {
    // El control que impide que el arreglo de arriba se pase de largo: el motor exige al menos una.
    const sinMapeo = {
      data: {
        partition: {
          strategy: { type: "columna", partition_col: "m", desarrollo: [], holdout: [], oot: [] },
        },
      },
    }
    const particion = decisionStatuses(scorecard, sinMapeo, SIN_VEREDICTO)[1]
    expect([particion.answered, particion.inProgress]).toEqual([false, true])
  })

  it("y una comparación normal sí exige su valor", () => {
    const sinValor = {
      data: { target: { bad_rule: { all_of: [{ col: "m", op: "==", value: "" }] } } },
    }
    expect(decisionStatuses(scorecard, sinValor, SIN_VEREDICTO)[0].inProgress).toBe(true)
  })

  it("una decisión que se contesta con un dato no ofrece formas", () => {
    for (const decision of porId("pd_lifetime").required_decisions) {
      if (decision.path.startsWith("survival.")) expect(decision.answer_forms).toEqual([])
    }
  })
})

describe("guardrail: elegir una forma escribe la plantilla del backend, no una compuesta aquí", () => {
  it("`ConfigTab` pasa la plantilla del catálogo a `setField`", () => {
    // Vitest corre sin DOM: se vigila el fuente, igual que el guardrail de montaje de abajo. Lo
    // que se protege es que el front NO componga el fragmento de dominio (SDD-23 §11) — si algún
    // día alguien construyera aquí el `Rule`, la interfaz y el motor podrían separarse en silencio.
    expect(configTabSource).toMatch(/onAnswerForm=\{\(path, template\) =>/)
    expect(configTabSource).toMatch(/setField\(path\.split\("\."\) as Path, template\)/)
    // ⚠️ Con D-COL-8 la plantilla puede llegar con sus huecos PROPUESTOS, y por eso ya no se pasa
    // `forma.template` crudo. El guardrail conserva su fuerza porque `plantillaConPrecargas` sólo
    // copia valores a rutas que el backend declaró: sigue sin haber dominio compuesto aquí, y la
    // única vía admitida está nombrada, así que componer a mano seguiría poniendo esto en rojo.
    expect(configTabSource).toMatch(
      /onAnswerForm\(\s*decision\.path,\s*plantillaConPrecargas\(forma\.template, propuesto\.propuestas\),\s*\)/,
    )
    expect(configTabSource).not.toMatch(/all_of|any_of|"columna"|"temporal"/)
  })
})

describe("guardrail: una decisión rechazada NO dice «te falta un dato» (D-RES-7)", () => {
  it("`ConfigTab` ramifica los tres estados y cita el motivo del motor", () => {
    // Vitest corre sin DOM, así que el copy se vigila en el fuente — mismo motivo y misma forma que
    // los dos guardrails vecinos. Lo que se protege es que el mensaje de hueco quede atado a
    // `inProgress` y NO se pueda volver a colgar de «no contestada», que es como nació la regresión.
    expect(configTabSource).toMatch(
      /\{decision\.inProgress \? \(\s*<p[^>]*>\s*Elegiste cómo contestarla; abajo te faltan los datos de tu cartera\./,
    )
    // El motivo se pinta TAL CUAL lo dio el motor. Si algún día alguien lo reescribe aquí, habrá
    // dos versiones del mismo mensaje y se separarán en silencio.
    expect(configTabSource).toMatch(/\{decision\.rejected \? \(/)
    expect(configTabSource).toMatch(/\{decision\.rejectionReason\}/)
    // Y el aria-label del icono distingue los tres, que es lo único que un lector de pantalla oye.
    expect(configTabSource).toMatch(/decision\.rejected\s*\?\s*"Revisa lo que escribiste"/)
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

describe("el esqueleto recorta los capítulos del informe (D-OBL-11)", () => {
  const CATALOGO_REAL = (FIXTURE_SCHEMA as { effective_defaults?: unknown })
    .effective_defaults as Parameters<typeof jobSkeleton>[2]

  it("un scorecard no exige el capítulo de una sección que no tiene", () => {
    // El default del motor son OCHO capítulos, entre ellos `eda`, que el trabajo no declara y el
    // formulario no ofrece. Sin el recorte, el paso `report` moría con `missing_policy: error` y
    // NINGÚN trabajo llegaba a `done`. Se descubrió corriendo el gate de aceptación, no en la suite.
    const job = porId("scorecard_pd")
    const skeleton = jobSkeleton({}, job, CATALOGO_REAL)
    const report = skeleton.report as { sections: { required_sections: string[] } }
    expect(report.sections.required_sections).not.toContain("eda")
    // Y lo que el trabajo SÍ produce se conserva: recortar no es vaciar.
    expect(report.sections.required_sections).toContain("binning")
    expect(report.sections.required_sections).toContain("scorecard")
    for (const capitulo of report.sections.required_sections) {
      expect(job.sections).toContain(capitulo)
    }
  })

  it("no AÑADE un capítulo que el default no pedía", () => {
    // El error simétrico: exigir un capítulo que el usuario nunca eligió.
    const job = porId("scorecard_pd")
    const skeleton = jobSkeleton({}, job, CATALOGO_REAL)
    const report = skeleton.report as { sections: { required_sections: string[] } }
    expect(report.sections.required_sections).not.toContain("data")
    expect(report.sections.required_sections).not.toContain("report")
  })

  it("un trabajo sin `report` no revienta", () => {
    const job: Job = { ...porId("scorecard_pd"), sections: ["data", "binning"] }
    expect(() => jobSkeleton({}, job, CATALOGO_REAL)).not.toThrow()
  })
})

describe("«Respondida» lo dice el motor, no sólo la forma del hueco (D-RES-1/2)", () => {
  const scorecard = porId("scorecard_pd")
  /** El veredicto tal como lo deja `buildErrorLookup` a partir de los `errors` de /api/validate. */
  const rechaza = (...locs: string[]): ValidationState => ({
    kind: "invalid",
    count: locs.length,
    lookup: new Map(locs.map((l) => [l, "mensaje del motor"])),
  })

  //: 🔴 Los casos se escriben A MANO, con su `loc` REAL medido contra el motor. Derivarlos del
  //: mismo criterio que se comprueba habría hecho el gate autorreferencial — la clase que este repo
  //: ya pagó dos veces. Cada fila es: qué valor, qué `loc` devuelve Pydantic, y qué se espera.
  const CASOS: {
    nombre: string
    path: string
    valor: unknown
    loc: string
    indice: number
  }[] = [
    {
      nombre: "una regla con las dos listas vacías",
      path: "data.target.bad_rule",
      valor: { all_of: [], any_of: [] },
      loc: "data.target.bad_rule",
      indice: 0,
    },
    {
      nombre: "una partición temporal sin sus campos",
      path: "data.partition.strategy",
      valor: { type: "temporal" },
      // ⚠️ Pydantic INSERTA el tag del discriminador: este `loc` no es un path del config.
      loc: "data.partition.strategy.temporal.date_col",
      indice: 1,
    },
    {
      // Sus huecos están AUSENTES, y un hueco ausente se ignora a propósito: es lo que permite no
      // adivinar qué forma eligió el usuario. Por eso el criterio de huecos no puede verlo.
      nombre: "una partición por cohortes sin ninguno de sus campos",
      path: "data.partition.strategy",
      valor: { type: "cohort" },
      loc: "data.partition.strategy.cohort.cohort_col",
      indice: 1,
    },
    {
      nombre: "🔴 al azar con fracciones que no suman 1 — la forma no declara NINGÚN hueco",
      path: "data.partition.strategy",
      valor: { type: "random", dev_fraction: 0.9, holdout_fraction: 0.9, oot_fraction: 0.9 },
      loc: "data.partition.strategy.random",
      indice: 1,
    },
    {
      nombre: "🔴 un tipo incorrecto en la raíz de la decisión",
      path: "data.target.bad_rule",
      valor: "una cadena donde va un objeto",
      loc: "data.target.bad_rule",
      indice: 0,
    },
  ]

  it("el barrido no es vacuo: sin el veredicto, TODOS estos casos decían «Respondida»", () => {
    // Ancla que da sentido a lo de abajo. Es el estado ANTERIOR, medido: son los falsos positivos
    // que el criterio de huecos no puede ver, y sin esta aserción el gate no probaría nada nuevo.
    for (const caso of CASOS) {
      const config = configCon(caso.path, caso.valor)
      const antes = decisionStatuses(scorecard, config, SIN_VEREDICTO)[caso.indice]
      expect(antes.answered, `${caso.nombre}: el criterio de huecos ya lo cazaba`).toBe(true)
    }
    expect(CASOS.length).toBeGreaterThanOrEqual(5)
  })

  it("con el veredicto del motor, ninguno queda contestado", () => {
    for (const caso of CASOS) {
      const config = configCon(caso.path, caso.valor)
      const estado = decisionStatuses(scorecard, config, rechaza(caso.loc))[caso.indice]
      expect([estado.answered, estado.inProgress], caso.nombre).toEqual([false, false])
      expect(estado.rejected, caso.nombre).toBe(true)
    }
  })

  it("🔴 RECHAZADA no es «te falta un dato»: a ninguno de estos le falta un hueco (D-RES-7)", () => {
    // La regresión que esto cierra: los cinco casos de arriba tienen la respuesta COMPLETA —el
    // ancla anti-vacua lo demuestra, sin veredicto salían «Respondida»— y aun así el copy decía
    // «abajo te faltan los datos de tu cartera», mandando al usuario a buscar un vacío inexistente.
    for (const caso of CASOS) {
      const config = configCon(caso.path, caso.valor)
      const estado = decisionStatuses(scorecard, config, rechaza(caso.loc))[caso.indice]
      expect(estado.inProgress, `${caso.nombre}: no le falta ningún hueco`).toBe(false)
      // Y el motivo llega a la tarjeta: para 4 de los 5 el `loc` lleva el tag del discriminador o
      // es un ancestro, así que ningún control de abajo lo pinta y éste es el único sitio.
      expect(estado.rejectionReason, caso.nombre).toBe("mensaje del motor")
    }
  })

  it("🔴 el HUECO gana al veredicto: es más específico y suele ser su causa", () => {
    // Los dos estados son excluyentes, y el orden importa. Una plantilla recién elegida tiene sus
    // huecos en blanco Y el motor la rechaza por eso mismo; decir «revisa lo que escribiste» sobre
    // algo que el usuario todavía no ha escrito sería la mentira simétrica de la que se corrigió.
    const forma = scorecard.required_decisions
      .find((d) => d.path === "data.target.bad_rule")!
      .answer_forms.find((f) => f.id === "columna_marcada")
    expect(forma, "el catálogo ya no trae la forma «columna_marcada»").toBeDefined()
    const conPlantilla = { data: { target: { bad_rule: forma!.template } } }
    const [badRule] = decisionStatuses(scorecard, conPlantilla, rechaza("data.target.bad_rule"))
    expect([badRule.answered, badRule.inProgress, badRule.rejected]).toEqual([false, true, false])
    expect(badRule.rejectionReason).toBeNull()
  })

  it("🔴 CONTROL POSITIVO: un config bueno sigue contestado, y con el motor conforme", () => {
    // Sin esto, un criterio que dijera «nunca contestada» pasaría todos los casos de arriba.
    const bueno = {
      data: {
        target: { bad_rule: { all_of: [{ col: "bad", op: "==", value: 1 }], any_of: [] } },
        partition: { strategy: { type: "random", dev_fraction: 0.7 } },
      },
    }
    for (const estado of decisionStatuses(scorecard, bueno, { kind: "valid", hash: "h", pipeline: null })) {
      expect([estado.answered, estado.inProgress, estado.rejected], estado.path).toEqual([
        true,
        false,
        false,
      ])
      expect(estado.rejectionReason, estado.path).toBeNull()
    }
  })

  it("un error de OTRA decisión no contamina a la vecina", () => {
    // Casar por prefijo tiene que ser estricto: `data.target` no es prefijo de `data.partition`.
    const bueno = {
      data: {
        target: { bad_rule: { all_of: [{ col: "bad", op: "==", value: 1 }], any_of: [] } },
        partition: { strategy: { type: "random", dev_fraction: 0.7 } },
      },
    }
    const estados = decisionStatuses(scorecard, bueno, rechaza("data.target.bad_rule.all_of.0.op"))
    expect(estados[0].answered).toBe(false)
    expect(estados[1].answered).toBe(true)
  })

  it("un error en un ANCESTRO no es de esta decisión", () => {
    // `data.target` puede fallar por un campo hermano; atribuírselo a `bad_rule` sería adivinar.
    const bueno = {
      data: { target: { bad_rule: { all_of: [{ col: "bad", op: "==", value: 1 }], any_of: [] } } },
    }
    expect(decisionStatuses(scorecard, bueno, rechaza("data.target"))[0].answered).toBe(true)
  })

  it("🔴 sin veredicto el estado NO se inventa (D-RES-4)", () => {
    // Marcar «no contestada» por no tener respuesta todavía haría parpadear la tarjeta en cada
    // tecleo, que es justo lo que el debounce de la validación existe para evitar.
    const bueno = {
      data: { target: { bad_rule: { all_of: [{ col: "bad", op: "==", value: 1 }], any_of: [] } } },
    }
    for (const estado of [{ kind: "idle" }, { kind: "checking" }, { kind: "unreachable" }] as const) {
      expect(decisionStatuses(scorecard, bueno, estado)[0].answered, estado.kind).toBe(true)
    }
  })

  it("una decisión sin empezar sigue «sin responder», no «te falta un dato»", () => {
    // El veredicto sólo entra cuando la clave existe: si no, el usuario ni ha empezado.
    const estados = decisionStatuses(scorecard, { data: {} }, rechaza("data.target.bad_rule"))
    expect([estados[0].answered, estados[0].inProgress, estados[0].rejected]).toEqual([
      false,
      false,
      false,
    ])
  })
})

/** Config mínimo con `valor` escrito en `path`, para los casos de arriba. */
function configCon(path: string, valor: unknown): Record<string, unknown> {
  const segmentos = path.split(".")
  const raiz: Record<string, unknown> = {}
  let nodo = raiz
  for (const segmento of segmentos.slice(0, -1)) {
    nodo[segmento] = {}
    nodo = nodo[segmento] as Record<string, unknown>
  }
  nodo[segmentos[segmentos.length - 1]] = valor
  return raiz
}
