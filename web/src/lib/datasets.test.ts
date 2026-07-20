import { describe, expect, it } from "vitest"

import type { DatasetInfo, UploadedDataset } from "./api"
import {
  datasetCatalogView,
  datasetOptionLabel,
  fromCatalog,
  fromUpload,
  isAllowedDataFile,
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
