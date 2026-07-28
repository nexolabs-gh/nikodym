import { describe, expect, it } from "vitest"

import type { PreflightMismatch } from "@/lib/api"
import {
  canJumpTo,
  candidateFieldIds,
  fieldIdForPath,
  mismatchCount,
  mismatchesForSection,
  preflightHeadline,
  runHint,
  sectionIsEditable,
  sectionOfPath,
  type PreflightState,
} from "@/lib/preflight"

/** Desajuste de prueba con la forma exacta que emite el motor (`core/dataset_check.py`). */
function mismatch(path: string, declared = "cohorte"): PreflightMismatch {
  return {
    path,
    declared,
    kind: "missing_column",
    message: `El dataset no tiene la columna «${declared}», que el config declara en ${path}.`,
  }
}

describe("fieldIdForPath", () => {
  it("deja intacto un path plano (ya coincide con el id del control)", () => {
    expect(fieldIdForPath("data.schema.index_col")).toBe("data.schema.index_col")
  })

  // La razón de existir de la función: el motor escribe los elementos de lista con corchetes
  // (`_declaraciones`) y `FieldRenderer` usa `path.join(".")` como `id`. Sin traducir, el salto
  // falla justo en el esquema de columnas, que es el caso más frecuente del recorrido medido.
  it("traduce los índices con corchetes a la convención del formulario", () => {
    expect(fieldIdForPath("data.schema.columns[3].name")).toBe(
      "data.schema.columns.3.name",
    )
  })

  it("traduce varios índices en el mismo path", () => {
    expect(fieldIdForPath("data.target.bad_rule.all_of[0].col")).toBe(
      "data.target.bad_rule.all_of.0.col",
    )
    expect(fieldIdForPath("a.b[1].c[12].d")).toBe("a.b.1.c.12.d")
  })
})

describe("candidateFieldIds", () => {
  it("un path plano tiene un único candidato: él mismo", () => {
    expect(candidateFieldIds("data.partition.strategy.cohort_col")).toEqual([
      "data.partition.strategy.cohort_col",
    ])
  })

  // ⚠️ El caso que obligó a existir a esta función, medido EN VIVO contra el servidor: el
  // formulario NO expande las listas de objetos. De `data.schema.columns[0].name` no hay ningún
  // control en el DOM; hay uno solo para la lista entera, con id `data.schema.columns`. Con sólo
  // el candidato exacto, el foco caía al `body` en 8 de los 15 desajustes del caso real.
  it("ofrece el control de la lista como respaldo del elemento", () => {
    expect(candidateFieldIds("data.schema.columns[0].name")).toEqual([
      "data.schema.columns.0.name",
      "data.schema.columns",
    ])
    expect(candidateFieldIds("data.target.bad_rule.all_of[0].col")).toEqual([
      "data.target.bad_rule.all_of.0.col",
      "data.target.bad_rule.all_of",
    ])
  })

  it("recorta un nivel de lista por vez, del más profundo al más superficial", () => {
    expect(candidateFieldIds("a.b[1].c[2].d")).toEqual([
      "a.b.1.c.2.d",
      "a.b.1.c",
      "a.b",
    ])
  })

  it("el primer candidato es siempre el más específico", () => {
    const [primero] = candidateFieldIds("data.schema.columns[3].name")
    expect(primero).toBe(fieldIdForPath("data.schema.columns[3].name"))
  })
})

describe("sectionOfPath", () => {
  it("toma el primer segmento como sección de config", () => {
    expect(sectionOfPath("data.partition.strategy.cohort_col")).toBe("data")
    expect(sectionOfPath("binning.feature_columns")).toBe("binning")
    expect(sectionOfPath("stability.temporal_column")).toBe("stability")
  })

  it("corta también cuando el primer separador es un corchete", () => {
    expect(sectionOfPath("data[0].x")).toBe("data")
  })

  it("devuelve el path entero si no tiene separadores", () => {
    expect(sectionOfPath("data")).toBe("data")
  })
})

describe("sectionIsEditable / canJumpTo", () => {
  it("reconoce las secciones que el formulario ofrece", () => {
    expect(sectionIsEditable("data")).toBe(true)
    expect(sectionIsEditable("binning")).toBe(true)
    expect(sectionIsEditable("provisioning_ifrs9")).toBe(true)
  })

  // `stability` fue el caso que destapó esto —era sección del camino F1 y no estaba en el
  // formulario, así que su desajuste se reportaba sin destino—, y por eso ahora SÍ está: lo exige
  // `tests/unit/test_column_roles.py::test_toda_seccion_en_alcance_del_preflight_es_navegable…`.
  it("las secciones del camino F1 son todas navegables", () => {
    expect(sectionIsEditable("stability")).toBe(true)
    expect(canJumpTo(mismatch("stability.temporal_column"))).toBe(true)
  })

  // Medido contra `GET /api/schema`: el backend expande 24 secciones y el formulario ofrece 13.
  // Las que quedan fuera están fuera del alcance del preflight, así que hoy no puede señalarlas;
  // si alguna entra (P5), el gate de Python obliga a ofrecerla antes.
  it("no declara editable una sección de config que el formulario no ofrece", () => {
    expect(sectionIsEditable("stress")).toBe(false)
    expect(sectionIsEditable("forward")).toBe(false)
    expect(canJumpTo(mismatch("stress.scenario_col"))).toBe(false)
  })

  it("tampoco declara editable una sección inexistente", () => {
    expect(sectionIsEditable("seccion_que_no_existe")).toBe(false)
  })

  it("sí permite saltar a un desajuste de una sección del formulario", () => {
    expect(canJumpTo(mismatch("data.partition.strategy.cohort_col"))).toBe(true)
  })
})

describe("mismatchesForSection", () => {
  const state: PreflightState = {
    kind: "issues",
    mismatches: [
      mismatch("data.schema.index_col", "loan_id"),
      mismatch("data.partition.strategy.cohort_col"),
      mismatch("binning.feature_columns", "renta"),
    ],
    uninspected: [],
  }

  it("filtra por sección", () => {
    expect(mismatchesForSection(state, "data")).toHaveLength(2)
    expect(mismatchesForSection(state, "binning")).toHaveLength(1)
    expect(mismatchesForSection(state, "selection")).toHaveLength(0)
  })

  it("no devuelve nada si el estado no trae desajustes", () => {
    expect(mismatchesForSection({ kind: "ok" }, "data")).toHaveLength(0)
    expect(mismatchesForSection({ kind: "checking" }, "data")).toHaveLength(0)
    expect(mismatchesForSection({ kind: "idle" }, "data")).toHaveLength(0)
    expect(mismatchesForSection({ kind: "unreachable" }, "data")).toHaveLength(0)
  })
})

describe("runHint", () => {
  // D-PRE-5: el aviso del botón advierte, y su copy dice explícitamente que se puede ejecutar.
  it("no dice nada cuando no hay desajustes", () => {
    expect(runHint({ kind: "ok" })).toBeNull()
    expect(runHint({ kind: "idle" })).toBeNull()
    expect(runHint({ kind: "checking" })).toBeNull()
    expect(runHint({ kind: "unreachable" })).toBeNull()
  })

  it("concuerda el singular y deja claro que no bloquea", () => {
    const hint = runHint({
      kind: "issues",
      mismatches: [mismatch("data.schema.index_col")],
      uninspected: [],
    })
    expect(hint).toContain("1 campo")
    expect(hint).toContain("Puedes ejecutar igual")
  })

  it("concuerda el plural", () => {
    const hint = runHint({
      kind: "issues",
      mismatches: [mismatch("data.a"), mismatch("data.b")],
      uninspected: [],
    })
    expect(hint).toContain("2 campos")
  })

  // `compatible=false` con CERO desajustes es un estado real (D-PRE-9): sólo secciones opacas.
  // Decir «no calza con 0 campos» sería absurdo; el copy tiene que hablar de lo no comparado.
  it("cubre el caso de sólo secciones no inspeccionadas", () => {
    const hint = runHint({ kind: "issues", mismatches: [], uninspected: ["binning"] })
    expect(hint).toContain("No se pudo comparar")
    expect(hint).not.toContain("0")
  })
})

describe("preflightHeadline", () => {
  it("afirma la compatibilidad cuando la hay", () => {
    expect(preflightHeadline({ kind: "ok" })).toContain("todas las columnas")
  })

  it("calla en los estados sin veredicto", () => {
    expect(preflightHeadline({ kind: "idle" })).toBeNull()
    expect(preflightHeadline({ kind: "checking" })).toBeNull()
    expect(preflightHeadline({ kind: "unreachable" })).toBeNull()
  })

  it("concuerda número en los desajustes", () => {
    expect(
      preflightHeadline({
        kind: "issues",
        mismatches: [mismatch("data.a")],
        uninspected: [],
      }),
    ).toContain("1 columna")
    expect(
      preflightHeadline({
        kind: "issues",
        mismatches: [mismatch("data.a"), mismatch("data.b")],
        uninspected: [],
      }),
    ).toContain("2 columnas")
  })
})

describe("mismatchCount", () => {
  it("cuenta sólo en el estado con desajustes", () => {
    expect(mismatchCount({ kind: "ok" })).toBe(0)
    expect(
      mismatchCount({
        kind: "issues",
        mismatches: [mismatch("data.a"), mismatch("data.b")],
        uninspected: [],
      }),
    ).toBe(2)
  })
})
