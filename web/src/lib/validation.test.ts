import { describe, expect, it } from "vitest"

import {
  buildErrorLookup,
  canRun,
  describeApiError,
  errorAtPath,
  pathKey,
  pipelineWarning,
  unanchoredError,
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

describe("unanchoredError", () => {
  // 🔴 Medido abriendo la pantalla: escribir la tasa objetivo con la fuente que la calcula sola
  // dejaba «Config inválido · 1 error» y NINGÚN mensaje visible. El `ConfigError` de una sección
  // lo levanta el `model_validator` sobre la sección entera, así que llega con `loc: []` y su
  // clave de lookup es la cadena vacía, que ningún campo del formulario reclama.
  const errorDeSeccion = {
    loc: [] as (string | number)[],
    msg: "anchor_source='development_observed' … el target_pd que fijó no se usaría.",
    type: "value_error",
  }

  it("recupera el error de sección, que no pertenece a ningún campo", () => {
    const state = {
      kind: "invalid" as const,
      count: 1,
      lookup: buildErrorLookup([errorDeSeccion]),
    }
    expect(unanchoredError(state)).toContain("no se usaría")
  })

  it("no inventa nada cuando todos los errores SÍ tienen campo", () => {
    const state = {
      kind: "invalid" as const,
      count: 1,
      lookup: buildErrorLookup([
        { loc: ["binning", "min_iv"], msg: "debe ser ≥ 0", type: "greater_than" },
      ]),
    }
    expect(unanchoredError(state)).toBeUndefined()
  })

  it("los estados que no son inválidos no tienen error suelto", () => {
    expect(unanchoredError({ kind: "idle" })).toBeUndefined()
    expect(unanchoredError({ kind: "checking" })).toBeUndefined()
    expect(unanchoredError({ kind: "unreachable" })).toBeUndefined()
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
