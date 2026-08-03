import { describe, expect, it } from "vitest"

import {
  artifactKey,
  carteraKeyMismatch,
  externalRefs,
  missingExternalInputs,
  plantillaConPrecargas,
  positionalInputs,
  precargasDeForma,
  requiredExternalArtifacts,
  withColumnMapping,
  type ExternalInput,
} from "@/lib/external-artifacts"
import {
  FIXTURE_JOBS,
  decisionStatuses,
  type AnswerForm,
  type ExternalArtifact,
  type Job,
} from "@/lib/jobs"

const jobs = FIXTURE_JOBS.jobs
const byId = (id: string): Job => {
  const job = jobs.find((j) => j.id === id)
  if (job === undefined) throw new Error(`el fixture no trae el trabajo ${id}`)
  return job
}

const PD: [string, string] = ["calibration", "calibrated_pd_frame"]
const SCORE: [string, string] = ["scorecard", "score"]

function input(overrides: Partial<ExternalInput> = {}): ExternalInput {
  return {
    datasetId: "uploaded_abc",
    fileName: "mi_modelo.csv",
    columns: ["id_operacion", "muestra", "malo", "probabilidad", "puntaje"],
    keyColumn: "id_operacion",
    ...overrides,
  }
}

describe("requiredExternalArtifacts", () => {
  it("sin trabajo elegido no pide nada", () => {
    expect(requiredExternalArtifacts(null, {})).toEqual([])
  })

  it("un trabajo sin insumo externo no pide nada", () => {
    expect(requiredExternalArtifacts(byId("scorecard_pd"), {})).toEqual([])
  })

  it("«validar un modelo» pide las dos claves, y ninguna es condicional", () => {
    const pedidos = requiredExternalArtifacts(byId("validar_modelo"), {})
    expect(pedidos.map((e) => e.artifact)).toEqual([PD, SCORE])
  })

  it("🔴 el método interno pide UNA clave U OTRA según de dónde salga la probabilidad", () => {
    // Es la razón de que `when` exista: fijar una sola clave rompería el trabajo en silencio en
    // cuanto alguien cambiara ese campo, y pedir las dos haría subir un archivo que nadie lee.
    const job = byId("provision_interna")
    const conCalibracion = requiredExternalArtifacts(job, {
      provisioning_internal: { pd_source: "calibration" },
    })
    const conModelo = requiredExternalArtifacts(job, {
      provisioning_internal: { pd_source: "model" },
    })
    expect(conCalibracion.map((e) => e.artifact)).toEqual([PD])
    expect(conModelo.map((e) => e.artifact)).toEqual([["model", "raw_pd_frame"]])
  })

  it("con la sección apagada no pide ninguna de las dos", () => {
    // Nada que pedir: sin sección no hay paso que consuma el resultado.
    expect(requiredExternalArtifacts(byId("provision_interna"), {})).toEqual([])
  })
})

describe("missingExternalInputs", () => {
  it("lista lo que falta subir", () => {
    const pedidos = requiredExternalArtifacts(byId("validar_modelo"), {})
    expect(missingExternalInputs(pedidos, {}).map((e) => e.artifact)).toEqual([PD, SCORE])
    const cubierto = { [artifactKey(PD)]: input() }
    expect(missingExternalInputs(pedidos, cubierto).map((e) => e.artifact)).toEqual([SCORE])
  })
})

describe("externalRefs", () => {
  it("manda una referencia por insumo PEDIDO y cubierto", () => {
    const pedidos = requiredExternalArtifacts(byId("validar_modelo"), {})
    const inputs = { [artifactKey(PD)]: input(), [artifactKey(SCORE)]: input() }
    expect(externalRefs(pedidos, inputs)).toEqual([
      { artifact: PD, dataset_id: "uploaded_abc", key_column: "id_operacion" },
      { artifact: SCORE, dataset_id: "uploaded_abc", key_column: "id_operacion" },
    ])
  })

  it("un archivo que quedó de otro trabajo NO se manda", () => {
    // El backend lo declararía inerte, y el usuario vería un aviso sobre algo que ya no pide.
    const pedidos = requiredExternalArtifacts(byId("scorecard_pd"), {})
    expect(externalRefs(pedidos, { [artifactKey(PD)]: input() })).toEqual([])
  })

  it("un insumo pedido sin archivo simplemente no viaja", () => {
    const pedidos = requiredExternalArtifacts(byId("validar_modelo"), {})
    expect(externalRefs(pedidos, {})).toEqual([])
  })
})

describe("positionalInputs", () => {
  it("señala los que se alinean por orden de filas", () => {
    const pedidos = requiredExternalArtifacts(byId("validar_modelo"), {})
    const inputs = {
      [artifactKey(PD)]: input({ keyColumn: null }),
      [artifactKey(SCORE)]: input(),
    }
    expect(positionalInputs(pedidos, inputs).map((e) => e.artifact)).toEqual([PD])
  })

  it("con llave declarada en todos, no hay nada que avisar", () => {
    const pedidos = requiredExternalArtifacts(byId("validar_modelo"), {})
    const inputs = { [artifactKey(PD)]: input(), [artifactKey(SCORE)]: input() }
    expect(positionalInputs(pedidos, inputs)).toEqual([])
  })
})

describe("withColumnMapping", () => {
  it("escribe la columna en todos los campos que el rol declara", () => {
    // Un rol, varios campos: `performance` y `stability` leen el MISMO archivo y nombran la misma
    // columna. Preguntarlo dos veces sería absurdo.
    const config = { performance: { pd_column: "x" }, stability: { pd_column: "x" } }
    const next = withColumnMapping(config, ["performance.pd_column", "stability.pd_column"], "prob")
    expect(next).toEqual({
      performance: { pd_column: "prob" },
      stability: { pd_column: "prob" },
    })
  })

  it("NO enciende una sección que el usuario dejó apagada", () => {
    // Activar una sección es un gesto de estructura suyo; escribirla aquí cambiaría el pipeline.
    const config = { performance: { pd_column: "x" }, stability: null }
    const next = withColumnMapping(config, ["performance.pd_column", "stability.pd_column"], "prob")
    expect(next).toEqual({ performance: { pd_column: "prob" }, stability: null })
  })

  it("no muta el config recibido", () => {
    const config = { performance: { pd_column: "x" } }
    withColumnMapping(config, ["performance.pd_column"], "prob")
    expect(config).toEqual({ performance: { pd_column: "x" } })
  })
})

describe("la llave tiene que estar en los dos archivos (D-PUE-6-bis)", () => {
  it("acusa la llave que la cartera no tiene, que es lo que impide emparejar", () => {
    expect(carteraKeyMismatch("id_op", ["otra", "saldo"])).toBe(true)
  })

  it("no acusa cuando la llave está en los dos, ni por orden de filas", () => {
    // Un aviso que se dispara de más se aprende a ignorar, así que los negativos importan tanto.
    expect(carteraKeyMismatch("id_op", ["id_op", "saldo"])).toBe(false)
    expect(carteraKeyMismatch(null, ["saldo"])).toBe(false)
  })

  it("con la cartera aún sin elegir no afirma nada", () => {
    // `undefined` es «todavía no sé qué columnas tiene», no «no tiene ninguna»: es la misma
    // distinción que el multiselect hace entre «no hay lista» y «la lista está vacía».
    expect(carteraKeyMismatch("id_op", undefined)).toBe(false)
  })
})

describe("el catálogo bundleado sostiene todo lo anterior", () => {
  it("los dos trabajos que traen un resultado de fuera están disponibles", () => {
    for (const id of ["provision_interna", "validar_modelo"]) {
      expect(byId(id).status).toBe("available")
      expect(byId(id).external_artifacts.length).toBeGreaterThan(0)
    }
  })

  it("cada insumo declara su pregunta de llave y al menos un rol que mapear", () => {
    const declarados: ExternalArtifact[] = jobs.flatMap((j) => j.external_artifacts)
    expect(declarados.length).toBeGreaterThanOrEqual(4)
    for (const entry of declarados) {
      expect(entry.key_question.endsWith("?")).toBe(true)
      expect(entry.columns.length).toBeGreaterThan(0)
      for (const columna of entry.columns) {
        expect(columna.question.endsWith("?")).toBe(true)
        expect(columna.config_paths.length).toBeGreaterThan(0)
      }
    }
  })
})

describe("pre-relleno cruzado desde un insumo externo (D-COL-8)", () => {
  const validar = byId("validar_modelo")
  const formaDe = (path: string, id: string): AnswerForm => {
    const forma = validar.required_decisions
      .find((d) => d.path === path)
      ?.answer_forms.find((f) => f.id === id)
    if (forma === undefined) throw new Error(`el fixture no trae la forma ${id} de ${path}`)
    return forma
  }
  const COLUMNA = formaDe("data.partition.strategy", "columna")
  const MARCADA = formaDe("data.target.bad_rule", "columna_marcada")
  const CARTERA = "uploaded_cartera"

  /** El config tal como queda tras mapear las columnas del archivo externo. */
  const mapeado = {
    performance: { partition_column: "muestra", target_column: "malo" },
    stability: { partition_column: "muestra" },
  }
  const mismoArchivo = { [artifactKey(PD)]: input({ datasetId: CARTERA }) }

  it("el catálogo declara las dos precargas, y ninguna otra forma trae ninguna", () => {
    // Ancla anti-tautología: si el fixture se quedara viejo, todo lo de abajo mediría el vacío.
    const conPrecargas = jobs.flatMap((j) =>
      j.required_decisions.flatMap((d) =>
        d.answer_forms.filter((f) => f.precargas.length > 0).map((f) => `${d.path}/${f.id}`),
      ),
    )
    expect([...new Set(conPrecargas)].sort()).toEqual([
      "data.partition.strategy/columna",
      "data.target.bad_rule/columna_marcada",
    ])
    expect(COLUMNA.precargas.map((p) => p.slot)).toEqual(["partition_col"])
    expect(MARCADA.precargas.map((p) => p.slot)).toEqual(["all_of.0.col"])
  })

  it("con el MISMO archivo que la cartera, propone la columna que el usuario ya nombró", () => {
    const propuesto = precargasDeForma(COLUMNA, mapeado, CARTERA, mismoArchivo)
    expect(propuesto.propuestas).toEqual([
      { slot: "partition_col", valor: "muestra", nota: COLUMNA.precargas[0].nota },
    ])
    expect(propuesto.motivo).toBeNull()
  })

  it("🔴 con OTRO archivo no propone nada, y dice por qué", () => {
    // La guarda que hace correcto todo esto: el motor lee esa columna de la CARTERA. Proponer una
    // del archivo externo cuando son archivos distintos es un error de categoría silencioso.
    const propuesto = precargasDeForma(COLUMNA, mapeado, CARTERA, {
      [artifactKey(PD)]: input({ datasetId: "uploaded_otro" }),
    })
    expect(propuesto.propuestas).toEqual([])
    expect(propuesto.motivo).not.toBeNull()
    expect(propuesto.motivo).toMatch(/no es el mismo/)
  })

  it("sin archivo subido no propone nada y tampoco explica nada", () => {
    // Callar aquí es lo correcto: el usuario todavía no ha hecho el gesto del que saldría la
    // propuesta, así que un aviso sería ruido sobre algo que no ha pasado.
    const propuesto = precargasDeForma(COLUMNA, mapeado, CARTERA, {})
    expect(propuesto).toEqual({ propuestas: [], motivo: null })
  })

  it("sin cartera elegida tampoco: no se sabe todavía si es el mismo archivo", () => {
    expect(precargasDeForma(COLUMNA, mapeado, null, mismoArchivo)).toEqual({
      propuestas: [],
      motivo: null,
    })
  })

  it("si la columna todavía no está mapeada, no hay nada que proponer", () => {
    expect(precargasDeForma(COLUMNA, {}, CARTERA, mismoArchivo).propuestas).toEqual([])
    expect(
      precargasDeForma(COLUMNA, { performance: { partition_column: "" } }, CARTERA, mismoArchivo)
        .propuestas,
    ).toEqual([])
  })

  it("🔴 el DEFAULT DEL MOTOR sembrado por el esqueleto no cuenta como respuesta del usuario", () => {
    // El defecto que sólo se vio ABRIENDO LA PANTALLA. El esqueleto del trabajo siembra
    // `performance.target_column = "target"` y `partition_column = "partition"` —los defaults del
    // motor—, así que «el campo no está en blanco» daba por contestado algo que el usuario no ha
    // tocado, y la propuesta salía con el rótulo «esto sale de lo que ya dijiste sobre tu archivo».
    //
    // El oráculo es el archivo del usuario, escrito a mano aquí: sus columnas NO incluyen `target`
    // ni `partition`, que es precisamente lo que delata al default.
    const esqueleto = {
      performance: { target_column: "target", partition_column: "partition" },
      stability: { partition_column: "partition" },
    }
    expect(input().columns).not.toContain("target")
    expect(input().columns).not.toContain("partition")
    expect(precargasDeForma(COLUMNA, esqueleto, CARTERA, mismoArchivo)).toEqual({
      propuestas: [],
      motivo: null,
    })
    expect(precargasDeForma(MARCADA, esqueleto, CARTERA, mismoArchivo)).toEqual({
      propuestas: [],
      motivo: null,
    })
  })

  it("🔴 y con OTRO archivo tampoco se explica nada mientras la columna siga sin mapear", () => {
    // Defecto encontrado EN LA PANTALLA, no en los tests: el aviso salía sobre la regla de malo
    // con la columna del incumplimiento todavía sin elegir. Explicar por qué no se propone algo
    // que aún no se podía proponer es ruido sobre algo que no ha pasado — y el docstring de
    // `precargasDeForma` prometía justo lo contrario de lo que el código hacía.
    const otro = { [artifactKey(PD)]: input({ datasetId: "uploaded_otro" }) }
    expect(precargasDeForma(MARCADA, {}, CARTERA, otro)).toEqual({ propuestas: [], motivo: null })
    // Y en cuanto la mapea, sí se le explica: ahí sí había de dónde proponer.
    expect(
      precargasDeForma(MARCADA, { performance: { target_column: "malo" } }, CARTERA, otro).motivo,
    ).not.toBeNull()
  })

  it("una forma sin precargas nunca propone, aunque haya archivo y coincida", () => {
    for (const id of ["temporal", "cohort", "random"]) {
      const forma = formaDe("data.partition.strategy", id)
      expect(precargasDeForma(forma, mapeado, CARTERA, mismoArchivo)).toEqual({
        propuestas: [],
        motivo: null,
      })
    }
  })

  it("🔴 CALCULAR la propuesta no escribe NADA en el config", () => {
    // Control negativo del invariante central: sin gesto del usuario el config sigue igual, y por
    // eso el estado de la decisión no se mueve por tener una propuesta disponible (D-OBL-5).
    const antes = structuredClone(mapeado)
    precargasDeForma(COLUMNA, mapeado, CARTERA, mismoArchivo)
    precargasDeForma(MARCADA, mapeado, CARTERA, mismoArchivo)
    expect(mapeado).toEqual(antes)
    expect(decisionStatuses(validar, mapeado as Record<string, unknown>)).toEqual(
      decisionStatuses(validar, antes as Record<string, unknown>),
    )
    for (const estado of decisionStatuses(validar, mapeado as Record<string, unknown>)) {
      expect([estado.answered, estado.inProgress]).toEqual([false, false])
    }
  })

  it("`plantillaConPrecargas` rellena el hueco sin tocar la plantilla del catálogo", () => {
    const original = structuredClone(COLUMNA.template)
    const salida = plantillaConPrecargas(COLUMNA.template, [
      { slot: "partition_col", valor: "muestra", nota: "n" },
    ])
    expect(salida).toEqual({
      type: "columna",
      partition_col: "muestra",
      desarrollo: [],
      holdout: [],
      oot: [],
    })
    expect(COLUMNA.template).toEqual(original)
    // Sin propuestas devuelve la plantilla tal cual: el camino de siempre no cambia.
    expect(plantillaConPrecargas(COLUMNA.template, [])).toBe(COLUMNA.template)
  })

  it("baja por índices de lista, que es donde vive el hueco de la regla", () => {
    expect(
      plantillaConPrecargas(MARCADA.template, [
        { slot: "all_of.0.col", valor: "malo", nota: "n" },
      ]),
    ).toEqual({ all_of: [{ col: "malo", op: "==", value: "" }], any_of: [] })
  })

  it("🔴 aceptar la propuesta NO deja la decisión contestada: falta el criterio institucional", () => {
    // El invariante que separa pre-rellenar de auto-contestar. El oráculo es el estado REAL que
    // calcula `decisionStatuses`, no la lista de slots: se aplica la plantilla propuesta al config
    // y se mide lo que el usuario vería.
    const conPropuesta = {
      ...mapeado,
      data: {
        partition: {
          strategy: plantillaConPrecargas(
            COLUMNA.template,
            precargasDeForma(COLUMNA, mapeado, CARTERA, mismoArchivo).propuestas,
          ),
        },
        target: {
          bad_rule: plantillaConPrecargas(
            MARCADA.template,
            precargasDeForma(MARCADA, mapeado, CARTERA, mismoArchivo).propuestas,
          ),
        },
      },
    }
    for (const estado of decisionStatuses(validar, conPropuesta as Record<string, unknown>)) {
      expect(
        [estado.answered, estado.inProgress],
        `${estado.path} quedó contestada sin gesto institucional`,
      ).toEqual([false, true])
    }

    // Y con el criterio institucional puesto —escrito A MANO, no derivado del catálogo— sí cierra.
    const completo = {
      data: {
        partition: {
          strategy: {
            type: "columna",
            partition_col: "muestra",
            desarrollo: ["DEV"],
            holdout: [],
            oot: [],
          },
        },
        target: { bad_rule: { all_of: [{ col: "malo", op: "==", value: 1 }], any_of: [] } },
      },
    }
    for (const estado of decisionStatuses(validar, completo)) {
      expect([estado.answered, estado.inProgress]).toEqual([true, false])
    }
  })
})
