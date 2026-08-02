import { describe, expect, it } from "vitest"

import {
  artifactKey,
  carteraKeyMismatch,
  externalRefs,
  missingExternalInputs,
  positionalInputs,
  requiredExternalArtifacts,
  withColumnMapping,
  type ExternalInput,
} from "@/lib/external-artifacts"
import { FIXTURE_JOBS, type ExternalArtifact, type Job } from "@/lib/jobs"

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
