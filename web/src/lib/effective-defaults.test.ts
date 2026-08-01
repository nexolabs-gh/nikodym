/**
 * Gate del resolver de defaults efectivos (enmienda DEFAULTS-EFECTIVOS-UI, D-FX-7/D-FX-8).
 *
 * Vitest corre sin DOM, así que aquí se prueba la LÓGICA que decide qué pinta cada widget —que es
 * donde vivían los dos defectos— y no el render. La matriz §3.2 de la enmienda se ejecuta entera
 * sobre `resolveValue`, porque todos los widgets consumen ese único helper: si uno se saliera del
 * carril, dejaría de estar cubierto por estos casos.
 *
 * Además se contrasta contra el fixture REAL del backend (`fixtures/schema.json`), no contra
 * catálogos de juguete: los dos casos vivos de F1 y la muestra adversarial del censo se comprueban
 * con los valores que el motor publica de verdad.
 */

import { describe, expect, it } from "vitest"

// El fuente del renderer como texto (`?raw` de Vite), para el guardrail estático del final.
import fieldRendererSource from "@/components/FieldRenderer.tsx?raw"

import {
  type DefaultsMap,
  type EffectiveDefaults,
  EFFECTIVE_DEFAULTS_VERSION,
  canonicalProjection,
  childMap,
  defMap,
  isDescriptor,
  nodeAtPath,
  resolveValue,
  usableCatalog,
} from "@/lib/effective-defaults"
import { FIXTURE_SCHEMA, configSectionSchema } from "@/lib/schema"
import {
  type JsonSchema,
  discriminatedBranchRef,
  itemRefName,
  refName,
  resolveRef,
  toggleMultiselect,
  unwrapNullable,
} from "@/lib/form-engine"

const CATALOGO = FIXTURE_SCHEMA.effective_defaults as EffectiveDefaults
const DEFS = FIXTURE_SCHEMA.json_schema.$defs ?? {}

/**
 * Baja por el schema real de la sección `data` siguiendo nombres de campo.
 *
 * ⚠️ No se indexa `properties.data.properties` a mano: una sección apagable viaja como
 * `anyOf: [<objeto>, null]` y ese camino da `undefined`. Es el mismo falso negativo que ya costó
 * declarar opaco lo que sí estaba expandido, y por eso se usan los helpers del propio front.
 */
function campo(ruta: string[]): JsonSchema {
  let nodo = configSectionSchema(FIXTURE_SCHEMA, "data")?.schema as JsonSchema
  for (const tramo of ruta) {
    const objeto = resolveRef(unwrapNullable(resolveRef(nodo, DEFS)).schema, DEFS)
    nodo = (objeto.properties ?? {})[tramo]
  }
  return nodo
}

/** Descriptor de prueba con default. */
const con = (value: unknown) => ({ has_default: true, value })
/** Descriptor de prueba SIN default (campo obligatorio). */
const sin = { has_default: false }

describe("resolveValue — matriz §3.2 de presencia y valores falsy", () => {
  // La tabla de la enmienda, fila por fila. La columna «escribe al render» no aparece porque el
  // resolver es una función pura: no puede escribir. Lo que sí se comprueba es que ninguna fila
  // caiga al default por ser falsy, que es lo que rompía `??` y la truthiness.
  const filas: {
    caso: string
    almacenado: unknown
    descriptor: unknown
    pinta: unknown
    origen: string
  }[] = [
    { caso: "boolean ausente", almacenado: undefined, descriptor: con(true), pinta: true, origen: "default" },
    { caso: "boolean false explícito", almacenado: false, descriptor: con(true), pinta: false, origen: "explicit" },
    { caso: "select ausente", almacenado: undefined, descriptor: con("show"), pinta: "show", origen: "default" },
    { caso: "texto vacío explícito", almacenado: "", descriptor: con("algo"), pinta: "", origen: "explicit" },
    { caso: "number ausente", almacenado: undefined, descriptor: con(7), pinta: 7, origen: "default" },
    { caso: "cero explícito", almacenado: 0, descriptor: con(7), pinta: 0, origen: "explicit" },
    {
      caso: "multiselect ausente",
      almacenado: undefined,
      descriptor: con(["eda", "binning"]),
      pinta: ["eda", "binning"],
      origen: "default",
    },
    {
      caso: "lista vacía explícita",
      almacenado: [],
      descriptor: con(["eda", "binning"]),
      pinta: [],
      origen: "explicit",
    },
    { caso: "null explícito", almacenado: null, descriptor: con("lo que sea"), pinta: null, origen: "explicit" },
    { caso: "default null", almacenado: undefined, descriptor: con(null), pinta: null, origen: "default" },
    { caso: "obligatorio sin default", almacenado: undefined, descriptor: sin, pinta: undefined, origen: "missing" },
    { caso: "sin catálogo", almacenado: undefined, descriptor: undefined, pinta: undefined, origen: "missing" },
  ]

  it.each(filas)("$caso", ({ almacenado, descriptor, pinta, origen }) => {
    const resultado = resolveValue(almacenado, descriptor as never)
    expect(resultado.displayed).toEqual(pinta)
    expect(resultado.provenance).toBe(origen)
  })

  it("un `null` explícito NUNCA cae al default, que es lo que rompía `??`", () => {
    // La línea vieja era `props.value ?? props.schema.default`: con `value === null` devolvía el
    // default y borraba visualmente una decisión del usuario.
    const explicito: string | null = null
    expect(resolveValue(explicito, con("show")).displayed).toBeNull()
    expect(explicito ?? "show").toBe("show") // el ancla de por qué el operador no servía
  })

  it("un mapa de hijos no es un default: el campo queda `missing`", () => {
    // Un submodelo no tiene valor propio que pintar; sus hojas se resuelven una a una.
    const resultado = resolveValue(undefined, { enabled: con(true) })
    expect(resultado.provenance).toBe("missing")
    expect(resultado.displayed).toBeUndefined()
  })
})

describe("isDescriptor / childMap", () => {
  it("descrimina por `has_default` BOOLEANO, no por su mera presencia", () => {
    expect(isDescriptor(con(1))).toBe(true)
    expect(isDescriptor(sin)).toBe(true)
    expect(isDescriptor({ enabled: con(true) })).toBe(false)
    // Un campo del config llamado `has_default` daría un dict, no un bool: sigue siendo un mapa.
    expect(isDescriptor({ has_default: con(true) })).toBe(false)
    expect(isDescriptor(undefined)).toBe(false)
    expect(isDescriptor(null)).toBe(false)
  })

  it("childMap devuelve el mapa sólo cuando el nodo NO es una hoja", () => {
    expect(childMap(con(1))).toBeUndefined()
    expect(childMap(undefined)).toBeUndefined()
    expect(childMap({ enabled: con(true) })).toEqual({ enabled: con(true) })
  })
})

describe("canonicalProjection — lo que se escribe al activar (D-FX-8)", () => {
  it("escribe todas las hojas con default y OMITE las obligatorias sin default", () => {
    const mapa: DefaultsMap = {
      enabled: con(true),
      threshold: con(0.75),
      nombre: sin,
      apagado: con(null),
    }
    expect(canonicalProjection(mapa)).toEqual({
      enabled: true,
      threshold: 0.75,
      apagado: null,
    })
  })

  it("baja recursivamente por los submodelos", () => {
    expect(
      canonicalProjection({ html: { render_charts: con(true), theme: con("nikodym") } }),
    ).toEqual({ html: { render_charts: true, theme: "nikodym" } })
  })

  it("sin catálogo devuelve un objeto vacío, no un objeto inventado", () => {
    expect(canonicalProjection(undefined)).toEqual({})
  })
})

describe("usableCatalog — una versión desconocida se ignora entera", () => {
  it("acepta la versión que este front sabe interpretar", () => {
    expect(usableCatalog(CATALOGO)?.version).toBe(EFFECTIVE_DEFAULTS_VERSION)
  })

  it("descarta una versión futura en vez de leerla a medias", () => {
    const futuro = { ...CATALOGO, version: EFFECTIVE_DEFAULTS_VERSION + 1 }
    expect(usableCatalog(futuro)).toBeUndefined()
    expect(nodeAtPath(futuro, ["report", "html", "render_charts"])).toBeUndefined()
  })

  it("sin catálogo no hay defaults que ofrecer (backend anterior)", () => {
    expect(usableCatalog(undefined)).toBeUndefined()
    expect(defMap(undefined, "data__ColumnSpec")).toBeUndefined()
  })
})

describe("nodeAtPath sobre el catálogo REAL del backend", () => {
  it("el fixture bundleado trae el catálogo", () => {
    // Si el fixture se quedara viejo, el formulario perdería TODOS los defaults sin avisar.
    expect(CATALOGO).toBeDefined()
    expect(CATALOGO.version).toBe(EFFECTIVE_DEFAULTS_VERSION)
    expect(Object.keys(CATALOGO.$defs).length).toBeGreaterThan(50)
  })

  it("los dos casos vivos de F1 que el formulario pintaba mal", () => {
    // `render_charts` se veía APAGADO y el motor corría con él activado.
    expect(nodeAtPath(CATALOGO, ["report", "html", "render_charts"])).toEqual({
      has_default: true,
      value: true,
    })
    // `placeholders` se veía EN BLANCO y el motor usaba «show».
    expect(nodeAtPath(CATALOGO, ["report", "document", "placeholders"])).toEqual({
      has_default: true,
      value: "show",
    })
  })

  it("las ocho secciones obligatorias del informe se pintan sin estar en el config", () => {
    const nodo = nodeAtPath(CATALOGO, ["report", "sections", "required_sections"])
    const { displayed, provenance } = resolveValue(undefined, nodo)
    expect(provenance).toBe("default")
    expect(displayed).toEqual([
      "eda",
      "binning",
      "selection",
      "model",
      "scorecard",
      "calibration",
      "performance",
      "stability",
    ])
  })

  it("muestra adversarial del censo: seis campos de cuatro dominios distintos", () => {
    const esperado: [string[], unknown][] = [
      [["model", "stepwise", "enabled"], true],
      [["selection", "correlation", "enabled"], true],
      [["selection", "vif", "threshold"], 5],
      [["provisioning_cmf", "matrices", "active_version"], "cmf_b1_b3_2025_01"],
      [["provisioning_ifrs9", "pd", "pit_mode"], "consume_pit"],
      [["provisioning_ifrs9", "staging", "dpd_default_backstop"], 90],
    ]
    for (const [ruta, valor] of esperado) {
      expect(nodeAtPath(CATALOGO, ruta)).toEqual({ has_default: true, value: valor })
    }
  })

  it("un submodelo apagable publica su `null`, no un mapa", () => {
    // Si publicara el mapa, el interruptor de `good_rule` aparecería ENCENDIDO sobre un objeto que
    // el motor no crea.
    expect(nodeAtPath(CATALOGO, ["data", "target", "good_rule"])).toEqual({
      has_default: true,
      value: null,
    })
    // Y su proyección para activarlo sigue disponible por `$defs`.
    expect(defMap(CATALOGO, "data__Rule")).toBeDefined()
  })

  it("un submodelo OBLIGATORIO publica descriptor y conserva sus hijos (D-OBL-2)", () => {
    // `data.target` es obligatorio: sin descriptor, la proyección canónica lo escribía entero y
    // producía un `bad_rule` vacío que el motor rechaza.
    const target = nodeAtPath(CATALOGO, ["data", "target"])
    expect(isDescriptor(target)).toBe(true)
    expect((target as { has_default: boolean }).has_default).toBe(false)
    expect(resolveValue(undefined, target).provenance).toBe("missing")

    // Pero sus hijos siguen alcanzables, o el formulario perdería sus defaults.
    expect(childMap(target)).toBeDefined()
    expect(nodeAtPath(CATALOGO, ["data", "target", "target_col"])).toEqual({
      has_default: true,
      value: "target",
    })
    // Y el mismo caso una vuelta más adentro.
    expect(nodeAtPath(CATALOGO, ["data", "target", "bad_rule", "all_of"])).toEqual({
      has_default: true,
      value: [],
    })
    // No era un defecto de `data`: `survival.input` es idéntico.
    expect(nodeAtPath(CATALOGO, ["survival", "input", "duration_col"])).toEqual({
      has_default: false,
    })
  })

  it("activar `data` ya no inventa un `bad_rule` que el motor rechaza", () => {
    const proyectado = canonicalProjection(childMap(nodeAtPath(CATALOGO, ["data"])))
    // Lo que sólo el usuario puede decidir NO se escribe (D-FX-8, ahora cumplible).
    expect(proyectado).not.toHaveProperty("target")
    expect(proyectado).not.toHaveProperty("partition")
    // Lo que sí tiene default se sigue escribiendo: la enmienda no vacía la proyección.
    expect(proyectado.schema).toMatchObject({ strict: false })
    expect(proyectado.missing).toMatchObject({ max_missing_rate: 0.99 })
  })

  it("añadir una fila de exclusión tampoco nace con una regla vacía", () => {
    // El mismo defecto vivía en otro gesto de estructura, y por eso el arreglo es del catálogo y no
    // del interruptor de sección.
    const fila = canonicalProjection(defMap(CATALOGO, "data__ExclusionRule"))
    expect(fila).not.toHaveProperty("rule")
    expect(fila).not.toHaveProperty("name")
  })

  it("se detiene en un tramo numérico: una fila de lista vive en `$defs`", () => {
    expect(nodeAtPath(CATALOGO, ["data", "schema", "columns", 0, "name"])).toBeUndefined()
    expect(defMap(CATALOGO, "data__ColumnSpec")?.name).toEqual({ has_default: false })
    expect(defMap(CATALOGO, "data__ColumnSpec")?.nullable).toEqual({
      has_default: true,
      value: true,
    })
  })

  it("una ruta inexistente no inventa nada", () => {
    expect(nodeAtPath(CATALOGO, ["report", "no_existe"])).toBeUndefined()
    expect(nodeAtPath(CATALOGO, ["seccion_fantasma", "campo"])).toBeUndefined()
  })
})

describe("las claves de `$defs` del catálogo son las del `json_schema`", () => {
  it("un `$ref` del schema resuelve en el catálogo", () => {
    // Es lo que permite al front alcanzar una fila de lista o una variante. Si las claves fueran
    // un identificador paralelo, `defMap` devolvería `undefined` en silencio.
    const clave = itemRefName(campo(["schema", "columns"]), DEFS)
    expect(clave).toBe("data__ColumnSpec")
    expect(defMap(CATALOGO, clave)).toBeDefined()
  })

  it("refName baja por la rama no nula y no por una unión discriminada", () => {
    expect(refName({ $ref: "#/$defs/data__ColumnSpec" })).toBe("data__ColumnSpec")
    expect(
      refName({ anyOf: [{ $ref: "#/$defs/data__Rule" }, { type: "null" }] }),
    ).toBe("data__Rule")
    // Dos ramas no nulas: la elige el usuario, no `refName`.
    expect(
      refName({ anyOf: [{ $ref: "#/$defs/A" }, { $ref: "#/$defs/B" }] }),
    ).toBeUndefined()
    expect(refName({ type: "string" })).toBeUndefined()
  })

  it("discriminatedBranchRef devuelve la clave de la rama elegida", () => {
    const clave = discriminatedBranchRef(campo(["partition", "strategy"]), "random", DEFS)
    expect(clave).toBe("data__RandomSplitConfig")
    expect(defMap(CATALOGO, clave)?.holdout_fraction).toEqual({
      has_default: true,
      value: 0.15,
    })
  })
})

describe("el primer gesto escribe, y escribe lo correcto", () => {
  it("quitar un chip de un multiselect VIRTUAL escribe la lista completa restante", () => {
    // D-FX-8. Pasar `props.value` (ausente) a `toggleMultiselect` escribía `[]` y borraba en
    // silencio las siete secciones que el usuario seguía viendo en pantalla.
    const nodo = nodeAtPath(CATALOGO, ["report", "sections", "required_sections"])
    const visibles = resolveValue(undefined, nodo).displayed as string[]
    const restante = toggleMultiselect(visibles, "eda", false, visibles)
    expect(restante).toEqual([
      "binning",
      "selection",
      "model",
      "scorecard",
      "calibration",
      "performance",
      "stability",
    ])
    expect(restante).toHaveLength(7)
  })

  it("activar una sección escribe su proyección canónica completa", () => {
    const mapa = childMap(nodeAtPath(CATALOGO, ["report"]))
    const escrito = canonicalProjection(mapa) as Record<string, Record<string, unknown>>
    expect(escrito.html.render_charts).toBe(true)
    expect(escrito.document.placeholders).toBe("show")
    expect(escrito.sections.required_sections).toHaveLength(8)
  })

  it("el resolver es puro: leer no muta el catálogo ni el valor", () => {
    const antes = JSON.stringify(CATALOGO)
    const config = { report: { output_dir: "informes" } }
    const copia = JSON.stringify(config)
    resolveValue(undefined, nodeAtPath(CATALOGO, ["report", "html", "render_charts"]))
    canonicalProjection(childMap(nodeAtPath(CATALOGO, ["report"])))
    expect(JSON.stringify(CATALOGO)).toBe(antes)
    expect(JSON.stringify(config)).toBe(copia)
  })
})

describe("el catálogo llega a TODOS los caminos del renderer (guardrail estático)", () => {
  // Vitest corre sin DOM, así que un campo que se quede sin catálogo no se puede cazar
  // renderizando. Y este defecto YA OCURRIÓ: `NullableField` llamaba a `FieldRenderer` sin pasarle
  // `defaultsBase`, de modo que los ~60 campos `X | None` perdían su default. Se veía en pantalla
  // —`binning.max_n_bins` pintaba el slider en 2 con la insignia «Predeterminado» mientras el motor
  // usaba 8— y ningún test lo notaba, porque los dos casos vivos de F1 cuelgan de grupos NO
  // nulables. El guardrail es de CLASE: cada punto donde el árbol se recorre a sí mismo tiene que
  // propagar el catálogo, o el gate se pone rojo.
  const usos = (tag: string) =>
    [...fieldRendererSource.matchAll(new RegExp(`<${tag}\\b[\\s\\S]*?/>`, "g"))].map((m) => m[0])

  /** El fuente sin comentarios: un detector que se acusa a sí mismo no vigila nada. */
  const codigo = fieldRendererSource
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .filter((l) => !l.trimStart().startsWith("//"))
    .join("\n")

  it("cada render recursivo propaga `defaultsBase` y `effectiveDefaults`", () => {
    const bloques = [...usos("FieldRenderer"), ...usos("GroupFieldList")]
    expect(bloques.length).toBeGreaterThanOrEqual(4)
    const sinCatalogo = bloques.filter(
      (b) => !b.includes("defaultsBase") || !b.includes("effectiveDefaults"),
    )
    expect(sinCatalogo).toEqual([])
  })

  it("ningún widget vuelve al `?? schema.default` que la enmienda prohíbe", () => {
    // D-FX-7: la lectura va por `resolveValue`, que decide por presencia de clave. `?? ` sobre el
    // valor almacenado confunde `null` explícito con ausencia.
    expect(codigo).not.toMatch(/props\.value\s*\?\?/)
    expect(codigo).not.toMatch(/value\s*\?\?\s*\w*[Ss]chema\.default/)
    // …y la lectura sí pasa por el resolver.
    expect(codigo).toMatch(/resolveValue\(props\.value, nodeFor\(props\)\)/)
  })

  it("el gate caza lo que promete", () => {
    // Ancla del detector contra el texto exacto del defecto que se corrigió.
    const roto = `<FieldRenderer name={name} schema={baseSchema} path={path} hideLabel />`
    expect(roto.includes("defaultsBase")).toBe(false)
    // Y el detector de `??` ve el patrón viejo cuando está en CÓDIGO, no en un comentario.
    expect("const v = props.value ?? props.schema.default").toMatch(/props\.value\s*\?\?/)
  })
})
