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
  }

  it("mapea id/n_rows y conserva el role de cada columna", () => {
    expect(fromCatalog(info)).toEqual({
      id: "consumo",
      name: "Consumo",
      nRows: 10000,
      columns: [
        { name: "edad", dtype: "int64", role: "feature" },
        { name: "default", dtype: "int64", role: "target" },
      ],
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
  }
  const HIPOTECARIO: DatasetInfo = {
    id: "hipotecario_4000",
    name: "Hipotecario",
    description: "Panel sintético hipotecario.",
    n_rows: 4000,
    columns: [{ name: "default", dtype: "int64", role: "target" }],
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
