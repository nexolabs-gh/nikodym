import { describe, expect, it } from "vitest"

import type { DatasetInfo, UploadedDataset } from "./api"
import {
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
