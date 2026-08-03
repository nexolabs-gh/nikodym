import { describe, expect, it } from "vitest"

import type { DatasetInfo, UploadedDataset } from "./api"
import {
  columnValuesByName,
  datasetCatalogView,
  datasetOptionLabel,
  fromCatalog,
  fromUpload,
  isAllowedDataFile,
  reconcileSelected,
  type SelectedDataset,
  columnasDeIndice,
  columnasOfrecibles,
} from "./datasets"

describe("isAllowedDataFile", () => {
  it("acepta .csv/.xlsx/.parquet, también en mayúsculas", () => {
    expect(isAllowedDataFile("panel.csv")).toBe(true)
    expect(isAllowedDataFile("panel.xlsx")).toBe(true)
    expect(isAllowedDataFile("panel.parquet")).toBe(true)
    expect(isAllowedDataFile("PANEL.CSV")).toBe(true)
    expect(isAllowedDataFile("Datos.XlSx")).toBe(true)
  })

  it("rechaza otras extensiones y archivos sin extensión", () => {
    expect(isAllowedDataFile("notas.txt")).toBe(false)
    expect(isAllowedDataFile("config.json")).toBe(false)
    expect(isAllowedDataFile("README")).toBe(false)
    expect(isAllowedDataFile("panel.csv.bak")).toBe(false)
  })
})

describe("fromCatalog", () => {
  const info: DatasetInfo = {
    id: "consumo",
    name: "Consumo",
    description: "Panel sintético de consumo.",
    n_rows: 10000,
    columns: [
      { name: "edad", dtype: "int64", role: "feature" },
      { name: "default", dtype: "int64", role: "target" },
    ],
    index_columns: [{ name: "loan_id", dtype: "int64", role: "id" }],
  }

  it("mapea id/n_rows, conserva el role y separa el ÍNDICE de las columnas", () => {
    expect(fromCatalog(info)).toEqual({
      id: "consumo",
      name: "Consumo",
      nRows: 10000,
      columns: [
        { name: "edad", dtype: "int64", role: "feature" },
        { name: "default", dtype: "int64", role: "target" },
      ],
      // D-PRO-1: el índice viaja aparte y NO se cuela entre las columnas — que es lo que hacía el
      // catálogo, y por eso la interfaz ofrecía `loan_id` como feature del binning.
      indexColumns: [{ name: "loan_id", dtype: "int64" }],
    })
  })
})

describe("fromUpload", () => {
  const resp: UploadedDataset = {
    dataset_id: "upload-abc123",
    name: "mi_panel.csv",
    n_rows: 512,
    columns: [
      { name: "score", dtype: "float64" },
      { name: "y", dtype: "int64" },
    ],
  }

  it("usa dataset_id como id y deja role undefined en cada columna", () => {
    const result = fromUpload(resp)
    expect(result).toEqual({
      id: "upload-abc123",
      name: "mi_panel.csv",
      nRows: 512,
      columns: [
        { name: "score", dtype: "float64", role: undefined },
        { name: "y", dtype: "int64", role: undefined },
      ],
      // Un CSV llega con `RangeIndex` sin nombre: no hay índice que nombrar, y decirlo con una
      // lista vacía es distinto de omitir el campo.
      indexColumns: [],
    })
    expect(result.columns.every((c) => c.role === undefined)).toBe(true)
  })
})

describe("los valores por columna llegan por las DOS rutas (D-COL-7)", () => {
  // A diferencia de `role` —que sólo trae el catálogo—, `values` lo traen las dos: es lo que
  // alimenta las opciones de un campo con `column_values_from`. Perderlo en cualquiera de los dos
  // normalizadores deja al usuario tecleando los valores a mano, que es justo lo que se arregló.
  it("fromCatalog conserva los valores de cada columna", () => {
    const info: DatasetInfo = {
      id: "consumo",
      name: "Consumo",
      description: "",
      n_rows: 10,
      columns: [
        { name: "muestra", dtype: "object", role: "feature", values: ["DEV", "OOT"] },
        { name: "edad", dtype: "int64", role: "feature" },
      ],
      index_columns: [],
    }
    const columnas = fromCatalog(info).columns
    expect(columnas[0].values).toEqual(["DEV", "OOT"])
    // Sin valores medidos queda `undefined` = «no se sabe», nunca `[]` inventado.
    expect(columnas[1].values).toBeUndefined()
  })

  it("fromUpload conserva los valores de cada columna", () => {
    const resp: UploadedDataset = {
      dataset_id: "upload-abc",
      name: "mi_panel.csv",
      n_rows: 10,
      columns: [
        { name: "muestra", dtype: "object", values: ["ENTRENAMIENTO", "VALIDACION"] },
        { name: "score", dtype: "float64" },
      ],
    }
    const columnas = fromUpload(resp).columns
    expect(columnas[0].values).toEqual(["ENTRENAMIENTO", "VALIDACION"])
    expect(columnas[1].values).toBeUndefined()
  })
})

describe("datasetOptionLabel", () => {
  it("combina el nombre y el número de filas", () => {
    const info: DatasetInfo = {
      id: "consumo",
      name: "Consumo",
      description: "",
      n_rows: 10000,
      columns: [],
      index_columns: [],
    }
    const label = datasetOptionLabel(info)
    expect(label).toContain("Consumo")
    expect(label).toContain("filas")
  })
})

describe("datasetCatalogView", () => {
  // Catálogo con el dataset del preset activo (consumo) y OTRO válido (hipotecario), para reproducir
  // el escenario del bug: estando el preset activo en consumo, poder elegir 'Hipotecario 4000'.
  const CONSUMO: DatasetInfo = {
    id: "consumo_10000",
    name: "Consumo",
    description: "Panel sintético de consumo.",
    n_rows: 10000,
    columns: [{ name: "default", dtype: "int64", role: "target" }],
    index_columns: [],
  }
  const HIPOTECARIO: DatasetInfo = {
    id: "hipotecario_4000",
    name: "Hipotecario",
    description: "Panel sintético hipotecario.",
    n_rows: 4000,
    columns: [{ name: "default", dtype: "int64", role: "target" }],
    index_columns: [],
  }
  const CATALOG: DatasetInfo[] = [CONSUMO, HIPOTECARIO]

  describe("backend real (demoMode=false): picker completo", () => {
    it("expone TODO el catálogo y refleja el datasetId elegido como value", () => {
      const view = datasetCatalogView(false, CATALOG, CONSUMO.id)
      expect(view.kind).toBe("picker")
      if (view.kind !== "picker") throw new Error("esperaba picker")
      expect(view.items.map((i) => i.value)).toEqual([
        CONSUMO.id,
        HIPOTECARIO.id,
      ])
      expect(view.value).toBe(CONSUMO.id)
    })

    it("permite elegir OTRO dataset del catálogo (p.ej. hipotecario) en modo real", () => {
      const view = datasetCatalogView(false, CATALOG, HIPOTECARIO.id)
      expect(view.kind).toBe("picker")
      if (view.kind !== "picker") throw new Error("esperaba picker")
      expect(view.value).toBe(HIPOTECARIO.id)
    })

    it("un id fuera del catálogo (una subida) deja el value en null, sin romper el picker", () => {
      const view = datasetCatalogView(false, CATALOG, "upload-abc123")
      expect(view.kind).toBe("picker")
      if (view.kind !== "picker") throw new Error("esperaba picker")
      expect(view.value).toBeNull()
      expect(view.items).toHaveLength(CATALOG.length)
    })
  })

  describe("demo estática (demoMode=true): bloqueado al preset activo", () => {
    it("NO expone un picker: queda locked (sin `items` para elegir otro dataset)", () => {
      const view = datasetCatalogView(true, CATALOG, CONSUMO.id)
      expect(view.kind).toBe("locked")
      // Estructuralmente no hay opciones que ofrecer → el usuario no puede setear otro dataset.
      expect(view).not.toHaveProperty("items")
      expect(view).not.toHaveProperty("value")
    })

    it("el dataset mostrado es SIEMPRE el del preset activo (el que cuelga de datasetId)", () => {
      const view = datasetCatalogView(true, CATALOG, CONSUMO.id)
      if (view.kind !== "locked") throw new Error("esperaba locked")
      expect(view.dataset).toEqual(CONSUMO)
      expect(view.dataset?.id).toBe(CONSUMO.id)
    })

    it("no se puede introducir un dataset incoherente: aunque el preset activo sea consumo, la vista jamás ofrece hipotecario", () => {
      const view = datasetCatalogView(true, CATALOG, CONSUMO.id)
      if (view.kind !== "locked") throw new Error("esperaba locked")
      // El único dataset expuesto es el del preset activo; 'Hipotecario 4000' no es alcanzable.
      expect(view.dataset?.id).not.toBe(HIPOTECARIO.id)
      expect(view).not.toHaveProperty("items")
    })

    it("si el preset activo cambia (datasetId=hipotecario), la vista sigue a ESE dataset", () => {
      const view = datasetCatalogView(true, CATALOG, HIPOTECARIO.id)
      if (view.kind !== "locked") throw new Error("esperaba locked")
      expect(view.dataset).toEqual(HIPOTECARIO)
    })

    it("degrada suave: datasetId null o desconocido → locked con dataset=null (nunca picker)", () => {
      const nullView = datasetCatalogView(true, CATALOG, null)
      expect(nullView.kind).toBe("locked")
      if (nullView.kind !== "locked") throw new Error("esperaba locked")
      expect(nullView.dataset).toBeNull()

      const unknownView = datasetCatalogView(true, CATALOG, "no-existe")
      expect(unknownView.kind).toBe("locked")
      if (unknownView.kind !== "locked") throw new Error("esperaba locked")
      expect(unknownView.dataset).toBeNull()
    })
  })
})

describe("reconcileSelected — el perfil que llega TARDE alcanza a la ficha activa", () => {
  // 🔴 El defecto que cierra: `GET /api/datasets` describe los datasets del catálogo SIN
  // materializar, así que en un workdir nuevo todas sus columnas llegan con `values: []`. Quien
  // materializa —y escribe el perfil— es el preflight, o sea DESPUÉS de que el usuario ya eligió.
  // Medido contra el backend: `list_datasets` da 0 columnas con valores antes de `materialize()` y
  // 4 después, sobre `consumo_comportamiento`.
  const SIN_PERFIL: DatasetInfo = {
    id: "consumo_comportamiento",
    name: "Consumo",
    description: "",
    n_rows: 10000,
    columns: [
      { name: "loan_id", dtype: "int64", role: "feature", values: [] },
      { name: "cohorte", dtype: "object", role: "feature", values: [] },
      { name: "bad_flag", dtype: "int64", role: "target", values: [] },
    ],
    index_columns: [],
  }
  const CON_PERFIL: DatasetInfo = {
    ...SIN_PERFIL,
    columns: [
      { name: "loan_id", dtype: "int64", role: "feature", values: [] },
      {
        name: "cohorte",
        dtype: "object",
        role: "feature",
        values: ["2023Q1", "2023Q2", "2024Q1"],
      },
      { name: "bad_flag", dtype: "int64", role: "target", values: ["0", "1"] },
    ],
    index_columns: [],
  }

  it("enriquece la ficha aunque el dataset NO haya cambiado", () => {
    const elegida = fromCatalog(SIN_PERFIL) // lo que el usuario eligió, sin perfil todavía
    expect(columnValuesByName(elegida)).toEqual({}) // el formulario no tiene nada que ofrecer

    const reconciliada = reconcileSelected(elegida, [CON_PERFIL])
    expect(reconciliada).not.toBe(elegida)
    expect(columnValuesByName(reconciliada)).toEqual({
      cohorte: ["2023Q1", "2023Q2", "2024Q1"],
      bad_flag: ["0", "1"],
    })
    // Y una columna sin valores medidos sigue fuera del mapa: «no se sabe», no «no tiene».
    expect(columnValuesByName(reconciliada)).not.toHaveProperty("loan_id")
  })

  it("devuelve la MISMA referencia cuando no hay nada que aportar (no hace bucle)", () => {
    // Es lo que impide que el efecto que la consume se re-dispare a sí mismo indefinidamente.
    const yaRica = fromCatalog(CON_PERFIL)
    expect(reconcileSelected(yaRica, [CON_PERFIL])).toBe(yaRica)
    // Catálogo aún sin cargar.
    expect(reconcileSelected(yaRica, [])).toBe(yaRica)
    // Y un catálogo que EMPOBRECE no puede pisar lo que ya se sabe.
    expect(reconcileSelected(yaRica, [SIN_PERFIL])).toBe(yaRica)
  })

  it("converge en UNA pasada (el efecto que la consume no se re-dispara solo)", () => {
    // El efecto de `DatosTab` hace `if (reconciliado !== selectedDataset) setSelectedDataset(...)`,
    // así que una segunda pasada que devolviera un objeto nuevo sería un bucle de render infinito.
    const primera = reconcileSelected(fromCatalog(SIN_PERFIL), [CON_PERFIL])
    const segunda = reconcileSelected(primera, [CON_PERFIL])
    expect(segunda).toBe(primera)
  })

  it("no toca un dataset SUBIDO (su id no está en el catálogo)", () => {
    // Las subidas nunca sufrieron el defecto —`POST /api/upload` mide el perfil en el acto— y
    // reconciliar no debe poder pisarlas.
    const subida = fromUpload({
      dataset_id: "upload-abc",
      name: "mi_panel.csv",
      n_rows: 10,
      columns: [{ name: "muestra", dtype: "object", values: ["DEV", "OOT"] }],
    })
    expect(reconcileSelected(subida, [CON_PERFIL])).toBe(subida)
    expect(columnValuesByName(subida)).toEqual({ muestra: ["DEV", "OOT"] })
  })

  it("sin ficha activa no inventa ninguna", () => {
    expect(reconcileSelected(null, [CON_PERFIL])).toBeNull()
    expect(columnValuesByName(null)).toBeUndefined()
  })
})

describe("columnasOfrecibles — los TRES conjuntos, medidos por separado (D-PRO-6)", () => {
  // 🔴 Al separar dos estados que estaban fundidos hay que probar LOS DOS, y aquí son tres. El
  // arreglo (que una columna producida deje de pintarse en rojo) tiene un simétrico que NO puede
  // perderse: dentro de `data` esa misma columna SÍ debe seguir acusándose, porque `DataStep`
  // valida su esquema antes de escribir nada (D-RAM-7). Un gate que sólo midiera el primero daría
  // verde habiendo roto el segundo.
  const DATASET: SelectedDataset = {
    id: "consumo",
    name: "Consumo",
    nRows: 10,
    columns: [
      { name: "ingreso", dtype: "float64" },
      { name: "mora", dtype: "int64" },
    ],
    indexColumns: [{ name: "loan_id", dtype: "int64" }],
  }
  // Oráculo escrito A MANO, no derivado de la función que se comprueba: es exactamente lo que el
  // backend publica para este config (`data` produce las cuatro y no se acredita a sí misma).
  const PRODUCIDAS = {
    data: [],
    survival: ["label_status", "partition", "target", "ttd"],
    stability: ["label_status", "partition", "target", "ttd"],
  }

  it("una columna del archivo se ofrece en cualquier sección", () => {
    expect(columnasOfrecibles(DATASET, PRODUCIDAS, "survival")).toContain("ingreso")
    expect(columnasOfrecibles(DATASET, PRODUCIDAS, "data")).toContain("ingreso")
  })

  it("una columna que produce el pipeline se ofrece FUERA de la sección que la escribe", () => {
    // El caso medido en pantalla: `survival.input.event_col = "target"` salía en rojo mientras el
    // backend decía compatible y la corrida llegaba a `done`.
    expect(columnasOfrecibles(DATASET, PRODUCIDAS, "survival")).toContain("target")
    expect(columnasOfrecibles(DATASET, PRODUCIDAS, "stability")).toContain("partition")
  })

  it("🔴 y NO se ofrece dentro de la sección que la escribe (D-RAM-7 no se pierde)", () => {
    const enData = columnasOfrecibles(DATASET, PRODUCIDAS, "data")
    expect(enData).not.toContain("target")
    expect(enData).not.toContain("partition")
  })

  it("el ÍNDICE no es una columna, y no se cuela en ninguna sección", () => {
    for (const seccion of ["data", "survival", "stability"]) {
      expect(columnasOfrecibles(DATASET, PRODUCIDAS, seccion)).not.toContain("loan_id")
    }
    expect(columnasDeIndice(DATASET)).toEqual(["loan_id"])
  })

  it("lo inventado sigue sin ofrecerse — el control negativo de siempre", () => {
    expect(columnasOfrecibles(DATASET, PRODUCIDAS, "survival")).not.toContain("columna_fantasma")
  })

  it("sin dataset no hay lista, y eso NO es una lista vacía", () => {
    // `undefined` = entrada libre; `[]` haría que el widget pintara «Sin opciones.» sobre un campo
    // perfectamente utilizable. La distinción ya costó un defecto con `feature_columns`.
    expect(columnasOfrecibles(null, PRODUCIDAS, "survival")).toBeUndefined()
    expect(columnasDeIndice(null)).toBeUndefined()
  })

  it("una sección sin entrada en el mapa no rompe: se queda con las del archivo", () => {
    expect(columnasOfrecibles(DATASET, PRODUCIDAS, "binning")).toEqual(["ingreso", "mora"])
    expect(columnasOfrecibles(DATASET, {}, "survival")).toEqual(["ingreso", "mora"])
  })

  it("no duplica una columna que el archivo ya trae y el pipeline también escribiría", () => {
    const conTarget: SelectedDataset = {
      ...DATASET,
      columns: [...DATASET.columns, { name: "target", dtype: "int64" }],
    }
    const ofrecidas = columnasOfrecibles(conTarget, PRODUCIDAS, "survival") ?? []
    expect(ofrecidas.filter((c) => c === "target")).toHaveLength(1)
  })
})
