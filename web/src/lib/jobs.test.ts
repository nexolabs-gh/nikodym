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
  methodologyStatuses,
  particionarPorJurisdiccion,
  sectionsOfJob,
  type Job,
} from "@/lib/jobs"
import landingSource from "@/components/LandingLauncher.tsx?raw"
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
    // El primer argumento tiene que seguir siendo `configSections`; los que vengan detrás son
    // ortogonales a esta invariante (D-VIS-4 añadió las secciones con error para marcarlas), y
    // atarse al número de argumentos convertiría este gate en un golden de la firma.
    expect(appSource).toMatch(/navItems\(configSections[,)]/)
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
    expect(configTabSource).toMatch(/\{decision\.rejected/)
    expect(configTabSource).toMatch(/decision\.rejectionReasons\.map/)
    // Y el aria-label del icono distingue los tres, que es lo único que un lector de pantalla oye.
    expect(configTabSource).toMatch(/decision\.rejected\s*\?\s*"Revisa lo que escribiste"/)
  })
})

describe("D-EXI-2: la opción que exige otro campo ofrece el salto a ese campo", () => {
  it("el catálogo declara el estado y su ruta, y no la deja en prosa", () => {
    // El dato, no el texto: la exigencia de estas tres ramas YA estaba escrita dentro de `help`, y
    // ahí no la puede leer ninguna máquina. Esto comprueba que ahora viaja como ruta.
    const punto = FIXTURE_JOBS.jobs
      .flatMap((job) => job.methodology_choices)
      .find((choice) => choice.path === "provisioning_internal.lgd.method")
    expect(punto).toBeDefined()
    const exigentes = punto!.options.filter((o) => o.estado === "exige_otro_campo")
    expect(exigentes).toHaveLength(3)
    for (const opcion of exigentes) {
      expect(opcion.exige.length).toBeGreaterThan(0)
      expect(opcion.exige[0]).toMatch(/^provisioning_internal\.lgd\./)
      // Y el motivo se lee en idioma de negocio, sin nombrar el campo del config.
      expect(opcion.motivo).toBeTruthy()
      expect(opcion.motivo).not.toMatch(/covariate_cols|recovery_col/)
    }
    // Control positivo del otro lado: las dos ramas observadas NO exigen nada.
    const observadas = punto!.options.filter((o) => o.estado === "disponible")
    expect(observadas).toHaveLength(2)
    for (const opcion of observadas) expect(opcion.exige).toEqual([])
  })

  it("`ConfigTab` pinta el salto SÓLO para la opción elegida y usa la ruta, no el path del punto", () => {
    // Vitest corre sin DOM, así que se vigila el fuente — misma forma y mismo motivo que los
    // guardrails vecinos. Lo que se protege son las dos mitades que hacen accionable el dato: que el
    // botón se pinte por `exige` y que salte a ESA ruta, no al campo del propio punto de elección.
    expect(configTabSource).toMatch(/opcion\.value === choice\.elegida && opcion\.exige\.length > 0/)
    expect(configTabSource).toMatch(/onFocus\(ruta\)/)
    expect(configTabSource).toMatch(/data-methodology-requires=\{ruta\}/)
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
    /** Qué estado le corresponde: le falta un hueco suyo, o está completa y el motor la rechaza. */
    estado: "inProgress" | "rejected"
  }[] = [
    {
      // Sin discriminador —las dos formas de `bad_rule` escriben la misma estructura—, así que los
      // slots ausentes no se pueden atribuir a ninguna: manda el criterio de siempre.
      nombre: "una regla con las dos listas vacías",
      path: "data.target.bad_rule",
      valor: { all_of: [], any_of: [] },
      loc: "data.target.bad_rule",
      indice: 0,
      estado: "rejected",
    },
    {
      // 🔴 Éste es el caso que la revisión adversarial cruzada destapó: le faltan `date_col` y
      // `oot_from` de verdad, y llamarlo «contestada pero rechazada» sería tan falso como el copy
      // que D-RES-7 vino a arreglar. Es unión discriminada, así que la forma SÍ se puede leer.
      nombre: "una partición temporal sin sus campos",
      path: "data.partition.strategy",
      valor: { type: "temporal" },
      // ⚠️ Pydantic INSERTA el tag del discriminador: este `loc` no es un path del config.
      loc: "data.partition.strategy.temporal.date_col",
      indice: 1,
      estado: "inProgress",
    },
    {
      nombre: "una partición por cohortes sin ninguno de sus campos",
      path: "data.partition.strategy",
      valor: { type: "cohort" },
      loc: "data.partition.strategy.cohort.cohort_col",
      indice: 1,
      estado: "inProgress",
    },
    {
      nombre: "🔴 al azar con fracciones que no suman 1 — la forma no declara NINGÚN hueco",
      path: "data.partition.strategy",
      valor: { type: "random", dev_fraction: 0.9, holdout_fraction: 0.9, oot_fraction: 0.9 },
      loc: "data.partition.strategy.random",
      indice: 1,
      estado: "rejected",
    },
    {
      // Una cadena donde va un objeto no lleva discriminador que leer, así que tampoco hay forma
      // elegida: cae al criterio de siempre y ningún hueco lo delata.
      nombre: "🔴 un tipo incorrecto en la raíz de la decisión",
      path: "data.target.bad_rule",
      valor: "una cadena donde va un objeto",
      loc: "data.target.bad_rule",
      indice: 0,
      estado: "rejected",
    },
  ]

  it("🔴 el barrido no es vacuo: sin el veredicto, los rechazados decían «Respondida»", () => {
    // Ancla que da sentido a lo de abajo: son los falsos positivos que el criterio de huecos NO
    // puede ver, y sin esta aserción el gate no probaría nada nuevo.
    //
    // 🔴 Y el ancla volvió a corregirme: cuando `huecosPendientes` aprendió a leer la forma elegida
    // de una unión discriminada, dos de los cinco casos pasaron a cazarse solos. Contarlos aquí
    // habría afirmado que el veredicto del motor aporta donde ya no aportaba.
    const soloVeredicto = CASOS.filter((c) => c.estado === "rejected")
    for (const caso of soloVeredicto) {
      const config = configCon(caso.path, caso.valor)
      const antes = decisionStatuses(scorecard, config, SIN_VEREDICTO)[caso.indice]
      expect(antes.answered, `${caso.nombre}: el criterio de huecos ya lo cazaba`).toBe(true)
    }
    expect(soloVeredicto.length).toBeGreaterThanOrEqual(3)
  })

  it("con el veredicto del motor, ninguno queda contestado", () => {
    for (const caso of CASOS) {
      const config = configCon(caso.path, caso.valor)
      const estado = decisionStatuses(scorecard, config, rechaza(caso.loc))[caso.indice]
      expect(estado.answered, caso.nombre).toBe(false)
    }
  })

  it("🔴 cada uno cae en SU estado: «te falta un dato» sólo con huecos de verdad (D-RES-7/8)", () => {
    // Las dos mitades de la regresión, juntas y en la misma tabla porque son la misma pregunta:
    //
    // * `random` con fracciones que no suman 1 NO tiene ningún hueco, y el copy decía «abajo te
    //   faltan los datos de tu cartera» — mandaba a buscar un vacío inexistente.
    // * `{type: "temporal"}` recién escrita SÍ tiene dos, y llamarla «Está contestada» es la
    //   mentira simétrica. Lo destapó la revisión adversarial cruzada sobre el primer arreglo.
    for (const caso of CASOS) {
      const config = configCon(caso.path, caso.valor)
      const estado = decisionStatuses(scorecard, config, rechaza(caso.loc))[caso.indice]
      expect(
        { inProgress: estado.inProgress, rejected: estado.rejected },
        caso.nombre,
      ).toEqual({
        inProgress: caso.estado === "inProgress",
        rejected: caso.estado === "rejected",
      })
      // El motivo llega a la tarjeta SÓLO cuando de verdad no falta nada: el `loc` lleva el tag del
      // discriminador o es un ancestro, así que ningún control de abajo lo pinta.
      expect(estado.rejectionReasons, caso.nombre).toEqual(
        caso.estado === "rejected" ? ["mensaje del motor"] : [],
      )
    }
  })

  it("🔴 los motivos se muestran TODOS, no sólo el primero", () => {
    // Quedarse con uno oculta diagnóstico justo en el caso que motiva la función: cuando ninguno
    // casa con un control, los demás no aparecen en ninguna parte. Lo señaló la revisión
    // adversarial cruzada sobre la primera versión, que devolvía `string | null`.
    const config = configCon("data.partition.strategy", {
      type: "random",
      dev_fraction: 0.9,
      holdout_fraction: 0.9,
      oot_fraction: 0.9,
    })
    const dos: ValidationState = {
      kind: "invalid",
      count: 2,
      lookup: new Map([
        ["data.partition.strategy.random", "las fracciones no suman 1"],
        ["data.partition.strategy.random.dev_fraction", "tiene que ser menor que 1"],
      ]),
    }
    expect(decisionStatuses(scorecard, config, dos)[1].rejectionReasons).toEqual([
      "las fracciones no suman 1",
      "tiene que ser menor que 1",
    ])
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
    expect(badRule.rejectionReasons).toEqual([])
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
      expect(estado.rejectionReasons, estado.path).toEqual([])
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

describe("el abanico metodológico en la pantalla (D-ABA-10)", () => {
  const punto = {
    path: "binning.method",
    question: "¿Cómo quieres agrupar los valores de cada variable?",
    help: "…",
    multiple: false,
    options: [
      {
        value: "optimal",
        label: "Óptimo",
        help: "…",
        estado: "disponible" as const,
        motivo: null,
        exige: [],
      },
      {
        value: "cp",
        label: "Programación por restricciones",
        help: "…",
        estado: "no_implementada" as const,
        motivo: "El motor la rechaza antes de empezar.",
        exige: [],
      },
    ],
    when: null,
  }
  const trabajo = { ...FIXTURE_JOBS.jobs[0], methodology_choices: [punto] }

  it("marca como elegida la opción que el config trae hoy", () => {
    const estados = methodologyStatuses(trabajo, { binning: { method: "optimal" } })
    expect(estados).toHaveLength(1)
    expect(estados[0].elegida).toBe("optimal")
  })

  it("no marca ninguna cuando la sección no está activa", () => {
    // `null` no es «ninguna elegida por el usuario»: es «aquí no hay config que leer». Inventar una
    // elegida pintaría un tilde sobre algo que el motor no va a usar.
    expect(methodologyStatuses(trabajo, { binning: null })[0].elegida).toBeNull()
    expect(methodologyStatuses(trabajo, {})[0].elegida).toBeNull()
  })

  it("🔴 un punto con `when` desaparece cuando su condición no se cumple (D-EXI-6)", () => {
    // El defecto que cierra: con `provisioning_internal.method='direct_loss_rate'` la subsección
    // `lgd` es INERTE —el motor no abre una sola columna suya— y el formulario seguía ofreciendo el
    // punto de la severidad; elegir ahí una rama modelada rechazaba el config ENTERO.
    const condicionado = {
      ...punto,
      path: "provisioning_internal.lgd.method",
      when: { path: "provisioning_internal.method", equals: "pd_lgd" },
    }
    const conCondicion = { ...FIXTURE_JOBS.jobs[0], methodology_choices: [condicionado] }

    // No aplica: el punto NO se ofrece.
    expect(
      methodologyStatuses(conCondicion, {
        provisioning_internal: { method: "direct_loss_rate" },
      }),
    ).toEqual([])
    // Aplica: el punto se ofrece igual que siempre.
    const aplica = methodologyStatuses(conCondicion, {
      provisioning_internal: { method: "pd_lgd" },
    })
    expect(aplica).toHaveLength(1)
    expect(aplica[0].path).toBe("provisioning_internal.lgd.method")
    // Y un punto SIN condición no se filtra nunca: el `when` no puede esconder lo que aplica siempre.
    expect(methodologyStatuses(trabajo, { binning: { method: "optimal" } })).toHaveLength(1)
  })

  it("una sección ausente NO hace desaparecer un punto condicionado por error", () => {
    // Control del caso frontera: sin `provisioning_internal` en el config, `valueAtPath` da
    // `undefined` y la condición no se cumple, así que el punto no se ofrece. Es lo correcto —no hay
    // método elegido todavía— pero conviene fijarlo: el criterio es «se cumple», no «no contradice».
    const condicionado = {
      ...punto,
      path: "provisioning_internal.lgd.method",
      when: { path: "provisioning_internal.method", equals: "pd_lgd" },
    }
    const job = { ...FIXTURE_JOBS.jobs[0], methodology_choices: [condicionado] }
    expect(methodologyStatuses(job, {})).toEqual([])
  })

  it("conserva el estado y el motivo que declara el catálogo, sin recalcularlos", () => {
    // El front no decide qué se puede usar: eso es dominio y lo mide el backend (D-ABA-5).
    const [estado] = methodologyStatuses(trabajo, { binning: { method: "optimal" } })
    expect(estado.options.map((o) => o.estado)).toEqual(["disponible", "no_implementada"])
    expect(estado.options[1].motivo).toContain("rechaza")
  })

  it("sin trabajo elegido no hay abanico que pintar", () => {
    expect(methodologyStatuses(null, { binning: { method: "optimal" } })).toEqual([])
  })

  it("🔴 se pinta DESPUÉS de las decisiones obligatorias, no antes", () => {
    // D-ABA-10: las obligatorias impiden correr y el abanico no. Ponerlo delante colocaría lo
    // opcional por delante de lo que bloquea, y eso no se puede comprobar renderizando —vitest
    // corre sin DOM—, así que se mide sobre el fuente.
    const obligatorias = configTabSource.indexOf("<RequiredDecisions")
    const abanico = configTabSource.indexOf("<MethodologyChoices")
    expect(obligatorias).toBeGreaterThan(-1)
    expect(abanico).toBeGreaterThan(-1)
    expect(abanico).toBeGreaterThan(obligatorias)
  })

  it("🔴 una opción no implementada no se puede pulsar, y su motivo se lee sin hover", () => {
    // D-JOB-5: se muestra, no se oculta —esconderla deja al usuario creyendo que la librería no la
    // contempla—. Pero mostrarla sin bloquearla sería peor: un clic que el motor rechaza después.
    const bloque = configTabSource.slice(
      configTabSource.indexOf("function MethodologyChoices"),
      configTabSource.indexOf("/** Descarga `text` como archivo"),
    )
    expect(bloque).toContain("disabled={bloqueada}")
    expect(bloque).toContain('opcion.estado === "no_implementada"')
    // El motivo va dentro del botón, no en un `title`: un tooltip no es leer.
    expect(bloque).toContain("{opcion.motivo}")
    expect(bloque).not.toContain("title={opcion.motivo}")
  })

  it("no enseña nunca el `path` (D-ABA-11)", () => {
    const bloque = configTabSource.slice(
      configTabSource.indexOf("function MethodologyChoices"),
      configTabSource.indexOf("/** Descarga `text` como archivo"),
    )
    // El `path` viaja en un atributo de datos para que Playwright pueda anclarse, y en la llamada
    // que enfoca el campo; lo que no puede es RENDERIZARSE como texto que el usuario lea.
    expect(bloque).not.toContain("{choice.path}<")
    expect(bloque).not.toContain(">{choice.path}")
  })
})

describe("la jurisdicción sale del listado principal, sin perder ningún trabajo", () => {
  it("la partición es EXHAUSTIVA: la unión es el catálogo entero, sin duplicados", () => {
    // La invariante que importa no es cómo se agrupa: es que agrupar no pueda desaparecer un
    // trabajo de la pantalla. Un trabajo que no cae en ningún bloque no se ve, y nada falla.
    const { estandar, porJurisdiccion } = particionarPorJurisdiccion(JOBS)
    const ids = [...estandar, ...porJurisdiccion].map((j) => j.id).sort()
    expect(ids).toEqual(JOBS.map((j) => j.id).sort())
    expect(new Set(ids).size).toBe(JOBS.length)
  })

  it("🔴 CONTROL NEGATIVO: una clave ausente no desaparece el trabajo", () => {
    // El catálogo llega por HTTP y el tipo no lo garantiza en runtime. Con dos filtros que se
    // creen opuestos (`=== null` / `!== null`), `undefined` cae fuera de los DOS y el trabajo se
    // esfuma. Este caso es la razón de que la partición use un predicado y su negación.
    const roto = { ...porId("scorecard_pd") } as Record<string, unknown>
    delete roto.jurisdiction_code
    const { estandar, porJurisdiccion } = particionarPorJurisdiccion([roto as unknown as Job])
    expect(estandar.length + porJurisdiccion.length).toBe(1)
    // Sin jurisdicción declarada, el sitio correcto es el listado principal.
    expect(estandar).toHaveLength(1)
  })

  it("separa exactamente los trabajos con jurisdicción, y hoy son los dos de CMF", () => {
    const { estandar, porJurisdiccion } = particionarPorJurisdiccion(JOBS)
    expect(porJurisdiccion.map((j) => j.id)).toEqual(["provisiones_cmf", "comparar_provisiones"])
    // `pd_y_lgd` usa el método interno, que es neutro: NO es un trabajo de jurisdicción.
    expect(estandar.map((j) => j.id)).toContain("pd_y_lgd")
    // Anti-vacuidad: si el catálogo perdiera su jurisdicción, los dos asserts de arriba pasarían
    // con listas vacías y este test dejaría de medir nada.
    expect(porJurisdiccion.length).toBeGreaterThan(0)
    expect(estandar.length).toBeGreaterThan(5)
  })

  it("🔴 la landing pinta DOS listas separadas, cada una de su propia partición", () => {
    // vitest corre sin DOM: que la pantalla pinte dos bloques se verificó con Playwright. Lo que
    // este guardrail impide es la regresión silenciosa —devolver la jurisdicción al listado
    // principal— con la suite en verde.
    //
    // 🔴 El bloque se delimita por el CIERRE REAL de la función, nunca por un `slice` de N
    // caracteres: medido, el cuerpo ocupa ~2.370 y una ventana de 2.400 deja 30 de margen. Con
    // 266 caracteres de JSX perfectamente plausible, el final de la función queda fuera de la
    // ventana y la regresión que este test dice impedir pasa en verde — el peor de los gates, el
    // que se cree presente.
    const inicio = landingSource.indexOf("function JobSelector")
    expect(inicio).toBeGreaterThan(-1)
    const resto = landingSource.slice(inicio + "function JobSelector".length)
    // La siguiente declaración de nivel de módulo, en cualquiera de sus formas: `JobSelector` es
    // hoy la última `function` suelta del archivo y la que sigue es `export default function`.
    const siguiente = resto.search(/\n(?:export\s+)?(?:default\s+)?(?:function|const|class)\s/)
    expect(siguiente).toBeGreaterThan(-1) // sin delimitador, el corte mentiría en silencio
    const bloque = resto.slice(0, siguiente)
    // El corte tiene que abarcar el cuerpo entero: si se quedara corto, el gate volvería a mirar
    // sólo el principio de la función, que es exactamente el defecto que este test corrige.
    expect(bloque).toContain("porJurisdiccion.length > 0")

    expect(bloque).toContain("particionarPorJurisdiccion(jobs)")

    // Y el invariante NO es «no digas `jobs.map`»: `[...estandar, ...porJurisdiccion].map(...)`
    // conserva la llamada a la partición, no contiene `jobs.map(` y devuelve la jurisdicción al
    // listado principal. Lo que se exige es que haya DOS renders y que sean los de cada mitad.
    const receptores = [...bloque.matchAll(/([A-Za-z_$\]][\w$\]]*)\s*\.map\(/g)].map((m) => m[1])
    expect(receptores.sort()).toEqual(["estandar", "porJurisdiccion"])
  })
})
