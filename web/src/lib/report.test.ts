import { describe, expect, it } from "vitest"

import { ApiError } from "./api"
import { REPORT_FILENAME, reportErrorMessage } from "./report"

describe("REPORT_FILENAME", () => {
  it("es un nombre fijo, independiente del run_id", () => {
    expect(REPORT_FILENAME).toBe("reporte-modelo.html")
  })
})

describe("reportErrorMessage", () => {
  it("ApiError 404 ⇒ mensaje claro de 'sin reporte' (no el HTTP crudo)", () => {
    const err = new ApiError("HTTP 404 en /api/report", 404)
    expect(reportErrorMessage(err)).toBe("Esta corrida no generó un reporte.")
  })

  it("ApiError no-404 con detalle en el body ⇒ describeApiError (detalle del backend)", () => {
    const err = new ApiError("HTTP 422 en /api/report", 422, {
      detail: "el reporte falló al renderizar",
    })
    expect(reportErrorMessage(err)).toBe("el reporte falló al renderizar")
  })

  it("ApiError no-404 sin body ⇒ cae al mensaje del error", () => {
    const err = new ApiError("HTTP 500 en /api/report", 500)
    expect(reportErrorMessage(err)).toBe("HTTP 500 en /api/report")
  })

  it("Error genérico (red) ⇒ su message", () => {
    expect(reportErrorMessage(new Error("Failed to fetch"))).toBe(
      "Failed to fetch",
    )
  })

  it("valor no-Error ⇒ su string", () => {
    expect(reportErrorMessage("boom")).toBe("boom")
  })
})
