import { describe, expect, it } from "vitest"

import fixtureSchema from "@/fixtures/schema.json"
import type { JsonSchema } from "@/lib/form-engine"

import {
  buildErrorLookup,
  canRun,
  describeApiError,
  errorAtPath,
  pathKey,
  erroresSinSuperficie,
  normalizarLoc,
  pipelineWarning,
  seccionesConError,
} from "./validation"

describe("pathKey", () => {
  it("une los segmentos con punto (misma clave para loc y path)", () => {
    expect(pathKey(["data", "load", "source"])).toBe("data.load.source")
  })

  it("conserva los índices numéricos de listas", () => {
    expect(pathKey(["binning", "rules", 2, "field"])).toBe(
      "binning.rules.2.field",
    )
  })

  it("segmentos vacíos ⇒ string vacío", () => {
    expect(pathKey([])).toBe("")
  })
})

describe("buildErrorLookup", () => {
  it("indexa cada error por pathKey(loc)", () => {
    const lookup = buildErrorLookup([
      { loc: ["binning", "min_iv"], msg: "debe ser ≥ 0", type: "greater_than" },
      { loc: ["model", "type"], msg: "tag desconocido", type: "union_tag" },
    ])
    expect(lookup.get("binning.min_iv")).toBe("debe ser ≥ 0")
    expect(lookup.get("model.type")).toBe("tag desconocido")
    expect(lookup.size).toBe(2)
  })

  it("concatena varios errores del mismo loc en orden", () => {
    const lookup = buildErrorLookup([
      { loc: ["data", "target"], msg: "requerido", type: "missing" },
      { loc: ["data", "target"], msg: "no puede ser vacío", type: "value_error" },
    ])
    expect(lookup.get("data.target")).toBe("requerido · no puede ser vacío")
  })

  it("lista vacía ⇒ lookup vacío", () => {
    expect(buildErrorLookup([]).size).toBe(0)
  })
})

describe("normalizarLoc (D-VIS-7): el tag del discriminador se elide", () => {
  // El fixture es el PAYLOAD de `/api/schema` (`{json_schema, defaults, …}`), no el schema: la raíz
  // del config es `json_schema`. Pasar el payload entero hace que `properties.data` no exista y el
  // recorrido se pierda en el primer segmento — lo cazó el ancla anti-vacuidad de este bloque.
  const raiz = (fixtureSchema as unknown as { json_schema: JsonSchema }).json_schema
  const defs = raiz.$defs ?? {}

  // 🔴 Medido contra la API viva: el motor devuelve el `loc` CON el tag de la variante, y
  // `DiscriminatedField` monta los controles SIN él. Son 58 hojas bajo las 3 uniones del config.
  it.each([
    [
      ["data", "partition", "strategy", "cohort", "holdout_fraction"],
      "data.partition.strategy.holdout_fraction",
    ],
    [
      ["data", "partition", "strategy", "temporal", "date_col"],
      "data.partition.strategy.date_col",
    ],
    [
      ["provisioning_internal", "lgd", "workout", "lgd_floor"],
      "provisioning_internal.lgd.lgd_floor",
    ],
  ])("%j ⇒ %s", (loc, esperado) => {
    expect(pathKey(normalizarLoc(loc, raiz, defs))).toBe(esperado)
  })

  // 🔴 Todas las ramas, no la primera. `workout` es la ÚLTIMA de las cinco de `lgd` y `columna` la
  // última de las cuatro de `partition.strategy`: un recolector que se quede con la primera rama
  // —el patrón que este repo pagó tres veces en una sesión— falla justo aquí.
  it("elide el tag de la ÚLTIMA rama, no sólo el de la primera", () => {
    expect(
      pathKey(normalizarLoc(["provisioning_internal", "lgd", "workout", "recovery_col"], raiz, defs)),
    ).toBe("provisioning_internal.lgd.recovery_col")
    expect(
      pathKey(normalizarLoc(["data", "partition", "strategy", "columna", "partition_col"], raiz, defs)),
    ).toBe("data.partition.strategy.partition_col")
  })

  it("un loc sin tag no se toca, y el índice de lista se conserva", () => {
    expect(pathKey(normalizarLoc(["binning", "min_iv"], raiz, defs))).toBe("binning.min_iv")
    expect(pathKey(normalizarLoc(["data", "schema", "columns", 3, "name"], raiz, defs))).toBe(
      "data.schema.columns.3.name",
    )
    expect(pathKey(normalizarLoc([], raiz, defs))).toBe("")
  })

  it("sin schema devuelve el loc tal cual: no se adivina", () => {
    expect(
      pathKey(normalizarLoc(["data", "partition", "strategy", "cohort", "holdout_fraction"], undefined)),
    ).toBe("data.partition.strategy.cohort.holdout_fraction")
  })

  // El tag se elide por POSICIÓN, no por nombre: un campo que se llame como un tag sobrevive.
  it("no borra un segmento que se llama como un tag pero NO está en la unión", () => {
    expect(pathKey(normalizarLoc(["data", "schema", "columns"], raiz, defs))).toBe(
      "data.schema.columns",
    )
    const inventado = ["provisioning_internal", "workout"]
    expect(pathKey(normalizarLoc(inventado, raiz, defs))).toBe("provisioning_internal.workout")
  })

  // Ancla anti-vacuidad: si el fixture dejara de traer las uniones, los `it.each` de arriba
  // pasarían por la rama «no se toca» y este bloque mediría nada.
  it("el fixture trae de verdad las tres uniones discriminadas", () => {
    const conTag = ["data", "partition", "strategy", "cohort", "holdout_fraction"]
    expect(normalizarLoc(conTag, raiz, defs)).toHaveLength(conTag.length - 1)
  })
})

describe("erroresSinSuperficie (D-VIS-1/2)", () => {
  // 🔴 Medido abriendo la pantalla, dos veces. (a) Un `ConfigError` de sección llega con `loc: []`
  // y ningún campo lo reclama —el caso de D-ANC-12—. (b) Y con D-EXI-5, un error que SÍ declara su
  // campo desaparece de la pantalla entera al mirar otra sección: quedaba «Config inválido · 1
  // error» y nada más, con el sidebar sin marcar. Anclar no puede costar la visibilidad.
  const errorDeSeccion = {
    loc: [] as (string | number)[],
    msg: "anchor_source='development_observed' … el target_pd que fijó no se usaría.",
    type: "value_error",
  }
  const errorDeCampo = {
    loc: ["binning", "min_iv"] as (string | number)[],
    msg: "debe ser ≥ 0",
    type: "greater_than",
  }
  const invalido = (errores: typeof errorDeCampo[]) => ({
    kind: "invalid" as const,
    count: errores.length,
    lookup: buildErrorLookup(errores),
  })

  it("publica el error de sección, que no pertenece a ningún campo", () => {
    const fuera = erroresSinSuperficie(invalido([errorDeSeccion]), "binning")
    expect(fuera).toHaveLength(1)
    expect(fuera[0].msg).toContain("no se usaría")
    expect(fuera[0].seccion).toBeNull()
    expect(fuera[0].alcanzable).toBe(false)
  })

  it("calla el error del campo cuando su sección es la ABIERTA: lo pinta el campo", () => {
    expect(erroresSinSuperficie(invalido([errorDeCampo]), "binning")).toEqual([])
  })

  it("🔴 publica el error del campo cuando el usuario mira OTRA sección", () => {
    const fuera = erroresSinSuperficie(invalido([errorDeCampo]), "data")
    expect(fuera).toHaveLength(1)
    expect(fuera[0].msg).toBe("debe ser ≥ 0")
    expect(fuera[0].seccion).toBe("binning")
    expect(fuera[0].seccionLabel).toBe("Optimal Binning")
    expect(fuera[0].alcanzable).toBe(true) // hay pestaña a la que saltar
  })

  it("una sección de dominio SIN pestaña se nombra, pero no se ofrece salto", () => {
    // `forward` es una de las 8 secciones que el formulario nunca pinta (19 `raise` viven ahí).
    // Ofrecer «ir al campo» sería mandar a una pestaña que no existe (criterio de preflight.ts:84).
    const fuera = erroresSinSuperficie(
      invalido([{ loc: ["forward", "scenarios"], msg: "faltan escenarios", type: "missing" }]),
      "binning",
    )
    expect(fuera[0].seccion).toBe("forward")
    expect(fuera[0].seccionLabel).toBeNull()
    expect(fuera[0].alcanzable).toBe(false)
  })

  it("los estados que no son inválidos no publican nada", () => {
    expect(erroresSinSuperficie({ kind: "idle" }, "data")).toEqual([])
    expect(erroresSinSuperficie({ kind: "checking" }, "data")).toEqual([])
    expect(erroresSinSuperficie({ kind: "unreachable" }, "data")).toEqual([])
  })

  // D-VIS-5: la invariante, con oráculo ESCRITO A MANO. No se deriva de `erroresSinSuperficie`,
  // que es justo lo que se está midiendo: un gate que rellena su esperado desde lo que comprueba
  // mide que la función es igual a sí misma.
  it("D-VIS-1: ningún error se queda fuera de las dos listas, mire donde mire el usuario", () => {
    const errores = [
      errorDeSeccion,
      errorDeCampo,
      { loc: ["data", "target", "bad_rule"], msg: "regla vacía", type: "value_error" },
      { loc: ["forward", "scenarios"], msg: "faltan escenarios", type: "missing" },
    ]
    const state = invalido(errores)
    const todas = ["data", "binning", "forward", "provisioning_internal", null]
    for (const seccionActiva of todas) {
      const publicados = new Set(erroresSinSuperficie(state, seccionActiva).map((e) => e.path))
      // Oráculo a mano: lo que el formulario ancla es exactamente lo de la sección abierta.
      const anclados = new Set(
        ["", "binning.min_iv", "data.target.bad_rule", "forward.scenarios"].filter(
          (clave) => clave !== "" && clave.split(".")[0] === seccionActiva,
        ),
      )
      const cubiertos = new Set([...publicados, ...anclados])
      expect(cubiertos.size).toBe(state.lookup.size)
      for (const clave of state.lookup.keys()) expect(cubiertos.has(clave)).toBe(true)
    }
  })
})

describe("seccionesConError (D-VIS-4)", () => {
  it("nombra las secciones con error y omite el error sin sección", () => {
    const state = {
      kind: "invalid" as const,
      count: 3,
      lookup: buildErrorLookup([
        { loc: ["binning", "min_iv"], msg: "a", type: "x" },
        { loc: ["binning", "max_n_bins"], msg: "b", type: "x" },
        { loc: ["forward", "scenarios"], msg: "c", type: "x" },
        { loc: [], msg: "de sección", type: "x" },
      ]),
    }
    expect(seccionesConError(state)).toEqual(new Set(["binning", "forward"]))
  })

  it("sin errores no marca nada", () => {
    expect(seccionesConError({ kind: "idle" }).size).toBe(0)
  })
})

describe("errorAtPath", () => {
  const lookup = buildErrorLookup([
    { loc: ["binning", "min_iv"], msg: "fuera de rango", type: "greater_than" },
  ])

  it("devuelve el msg cuando el path matchea un loc", () => {
    expect(errorAtPath(lookup, ["binning", "min_iv"])).toBe("fuera de rango")
  })

  it("devuelve undefined cuando no matchea", () => {
    expect(errorAtPath(lookup, ["binning", "max_bins"])).toBeUndefined()
  })

  it("lookup ausente ⇒ undefined (sin crashear)", () => {
    expect(errorAtPath(undefined, ["binning", "min_iv"])).toBeUndefined()
  })
})

describe("describeApiError (422 de los endpoints YAML)", () => {
  it("detail string (mensaje del motor) ⇒ se devuelve tal cual", () => {
    const body = { detail: "el schema_version 0 no soporta migración" }
    expect(describeApiError(body, "fallback")).toBe(
      "el schema_version 0 no soporta migración",
    )
  })

  it("detail lista [{loc,msg}] ⇒ se formatea loc: msg por línea", () => {
    const body = {
      detail: [
        { loc: ["binning", "min_iv"], msg: "debe ser ≥ 0", type: "greater_than" },
        { loc: ["model"], msg: "requerido", type: "missing" },
      ],
    }
    expect(describeApiError(body, "fallback")).toBe(
      "binning.min_iv: debe ser ≥ 0; model: requerido",
    )
  })

  it("cuerpo no reconocido ⇒ fallback", () => {
    expect(describeApiError(null, "fallback")).toBe("fallback")
    expect(describeApiError({ detail: [] }, "fallback")).toBe("fallback")
    expect(describeApiError({ other: 1 }, "fallback")).toBe("fallback")
  })
})

describe("canRun (gate de la corrida, SDD §8)", () => {
  it("config válido + dataset ⇒ ok, sin motivo", () => {
    expect(canRun({ kind: "valid", hash: "abc123", pipeline: null }, "consumo")).toEqual({
      ok: true,
    })
  })

  it("arranque en curso (idle/checking) ⇒ bloquea con un motivo TRANSITORIO", () => {
    // Desde UX1 el config se siembra y valida solo al entrar: `idle` ya no significa "no
    // configuraste" (eso sería un peaje inexistente), sino "el arranque todavía no termina".
    expect(canRun({ kind: "idle" }, "consumo")).toEqual({
      ok: false,
      reason: "Preparando la configuración…",
    })
    expect(canRun({ kind: "checking" }, "consumo")).toEqual({
      ok: false,
      reason: "Validando la configuración…",
    })
  })

  it("config inválido o backend caído ⇒ bloquea con el motivo REAL, aunque haya dataset", () => {
    expect(
      canRun({ kind: "invalid", count: 2, lookup: new Map() }, "consumo"),
    ).toEqual({
      ok: false,
      reason: "El config tiene errores: revísalo en Configuración",
    })
    expect(canRun({ kind: "unreachable" }, "consumo")).toEqual({
      ok: false,
      reason: "Sin backend: no se pudo validar el config",
    })
  })

  it("config válido pero sin dataset (null o vacío) ⇒ bloquea por dataset", () => {
    expect(canRun({ kind: "valid", hash: "abc123", pipeline: null }, null)).toEqual({
      ok: false,
      reason: "Falta elegir dataset",
    })
    expect(canRun({ kind: "valid", hash: "abc123", pipeline: null }, "")).toEqual({
      ok: false,
      reason: "Falta elegir dataset",
    })
  })

  it("prioriza el motivo del config sobre el del dataset", () => {
    expect(canRun({ kind: "idle" }, null)).toEqual({
      ok: false,
      reason: "Preparando la configuración…",
    })
  })
})

describe("pipelineWarning (aviso de config inejecutable, D-PIPE-2/D-PIPE-5)", () => {
  const inejecutable = {
    executable: false,
    steps: [],
    message:
      "El paso 'provisioning_ifrs9' requiere ('survival', 'term_structure'), que ningún paso aguas arriba produce: config inejecutable.",
    inert_artifacts: [],
  }

  it("publica el mensaje del motor cuando el config no es ejecutable", () => {
    expect(
      pipelineWarning({ kind: "valid", hash: "abc", pipeline: inejecutable }),
    ).toBe(inejecutable.message)
  })

  it("calla si el config es ejecutable", () => {
    expect(
      pipelineWarning({
        kind: "valid",
        hash: "abc",
        pipeline: {
          executable: true,
          steps: ["data", "binning"],
          message: null,
          inert_artifacts: [],
        },
      }),
    ).toBeNull()
  })

  it("calla si el backend no informó pipeline (demo o backend anterior)", () => {
    // `null` es "sin información", no "inejecutable": un aviso inventado es peor que ninguno.
    expect(pipelineWarning({ kind: "valid", hash: "abc", pipeline: null })).toBeNull()
  })

  it("calla mientras el config no es válido: sin modelo no hay pipeline que resolver", () => {
    expect(
      pipelineWarning({ kind: "invalid", count: 1, lookup: new Map() }),
    ).toBeNull()
    expect(pipelineWarning({ kind: "checking" })).toBeNull()
    expect(pipelineWarning({ kind: "idle" })).toBeNull()
    expect(pipelineWarning({ kind: "unreachable" })).toBeNull()
  })

  it("NO bloquea la corrida: canRun ignora la ejecutabilidad (D-PIPE-4)", () => {
    // El motor es la autoridad y desde D-ERR-8 registra el intento fallido con su diagnóstico;
    // bloquear aquí le quitaría al usuario el intento y su audit-trail.
    expect(
      canRun({ kind: "valid", hash: "abc", pipeline: inejecutable }, "consumo"),
    ).toEqual({ ok: true })
  })
})
