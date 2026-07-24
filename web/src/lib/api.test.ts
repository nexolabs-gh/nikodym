/**
 * Contrato del token de sesión en el front (enmienda B2.2, E-B2.2-7 y E-B2.2-9).
 *
 * Dos reglas que, si se rompen, no las caza ningún otro gate:
 *  1. `API_BASE` es relativo. Cuando caía a `http://localhost:8000`, ese literal viajaba en el
 *     bundle distribuido y la UI instalada quedaba con toda la API muerta.
 *  2. El placeholder sin sustituir cuenta como *ausencia* de token. En la demo estática nadie lo
 *     sustituye; tratarlo como credencial haría que `demo.nikodym.cl` mandara
 *     `X-Nikodym-Token: __NIKODYM_TOKEN__` en cada llamada.
 *
 * El entorno de vitest es `node` (sin DOM) y no se añade `jsdom` sólo para esto: meter una
 * dependencia al lock —con sus gates de licencias y supply-chain— por un test es peor negocio que
 * un doble de tres líneas. Lo que se ejercita aquí es la lógica de `sessionToken` (trim,
 * placeholder, vacío), no la implementación del DOM.
 */

import { afterEach, describe, expect, it } from "vitest"

import { API_BASE, sessionToken, tokenHeaders } from "@/lib/api"

const PLACEHOLDER = "__NIKODYM_TOKEN__"

/** Instala un `document` mínimo cuyo `querySelector` devuelve un meta con `content`. */
function conMeta(content: string | null): void {
  const doble = {
    querySelector: () => (content === null ? null : { getAttribute: () => content }),
  }
  Reflect.set(globalThis, "document", doble)
}

afterEach(() => {
  Reflect.deleteProperty(globalThis, "document")
})

describe("API_BASE", () => {
  it("es relativo: nunca un origen absoluto", () => {
    expect(API_BASE).toBe("")
  })
})

describe("sessionToken", () => {
  it("devuelve null sin document (la demo prerenderizada)", () => {
    expect(sessionToken()).toBeNull()
    expect(tokenHeaders()).toEqual({})
  })

  it("devuelve null si no hay meta en el index", () => {
    conMeta(null)

    expect(sessionToken()).toBeNull()
    expect(tokenHeaders()).toEqual({})
  })

  it("trata el placeholder sin sustituir como ausencia de token", () => {
    conMeta(PLACEHOLDER)

    expect(sessionToken()).toBeNull()
    expect(tokenHeaders()).toEqual({})
  })

  it("devuelve el token cuando el launcher lo inyectó", () => {
    conMeta("token-real-de-la-sesion")

    expect(sessionToken()).toBe("token-real-de-la-sesion")
    expect(tokenHeaders()).toEqual({ "X-Nikodym-Token": "token-real-de-la-sesion" })
  })

  it("ignora un meta vacío o con sólo espacios", () => {
    conMeta("   ")

    expect(sessionToken()).toBeNull()
  })
})
