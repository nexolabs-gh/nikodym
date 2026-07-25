/**
 * Espejo en el front del contrato de marcas de `src/nikodym/core/markers.py`.
 *
 * `FALTA-DATO` es lo que debe Nikodym (brecha del motor) y `DATO-INSTITUCIONAL` lo que debe la
 * institución. Son identificadores internos: viajan en `warning_codes` para que el motor y la UI se
 * entiendan, y **no se le muestran al lector** — a él se le explica la limitación en su idioma.
 *
 * Esta es la ÚNICA definición de las marcas en el front: el resto del código la importa en vez de
 * escribir el literal, igual que las capas Python consumen `is_declared_warning()`. Un filtro que
 * conozca una sola marca descarta la otra en silencio, sin fallar, y ese es justo el modo de fallo
 * que el contrato quiere evitar.
 *
 * `public-copy.test.ts` verifica que esta lista coincida con la del contrato Python, así que una
 * tercera marca allá pone rojo aquí en vez de abrir un hueco mudo.
 */

/** Las dos marcas de aviso declarado, en el orden de `DECLARED_MARKERS`. */
export const MARCAS_DECLARADAS = ["FALTA-DATO", "DATO-INSTITUCIONAL"] as const

/** Reconoce un código de aviso declarado, con o sin sufijo de familia. */
export function esAvisoDeclarado(texto: string): boolean {
  return MARCAS_DECLARADAS.some((marca) => texto.includes(marca))
}
