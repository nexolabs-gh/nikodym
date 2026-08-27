import { expect, test, type ConsoleMessage, type Request, type Response } from "@playwright/test"

/**
 * B2.4 — clean-room de la interfaz distribuida.
 *
 * Lo que este arnés cubre y ninguno de los gates anteriores cubría: **que el bundle JS/CSS que
 * viaja dentro del wheel se ejecute**. Hasta la 1.11.0 el árbol de `nikodym/ui/static` se verificaba
 * por SHA-256 contra su procedencia y no lo cargaba jamás un navegador; `vitest` corre sin DOM y
 * `scripts/smoke_instalacion_pip.py` llama a la app in-process con `TestClient`. Un bundle íntegro
 * pero roto —un import muerto, un asset renombrado, una API de React mal empaquetada— pasaba los
 * dieciséis jobs y llegaba a PyPI.
 *
 * El servidor lo levanta quien invoca el arnés, desde un venv con el wheel candidato instalado
 * FUERA del checkout, y su URL llega por `NIKODYM_UI_URL`.
 */

/** Errores de consola que no son defectos del producto y que ignorar aquí no esconde nada. */
const RUIDO_TOLERADO = [
  // React DevTools en Chromium headless.
  /Download the React DevTools/i,
  // El visor del informe es un `<iframe srcDoc sandbox="">`, con TODAS las restricciones activas
  // a propósito: un `srcdoc` hereda el origen del padre, así que dejarlo ejecutar scripts sería
  // darle el origen de la app a un HTML generado (`ReporteTab.tsx:317-323`). Chromium registra el
  // bloqueo como error de consola; aquí es la prueba de que la guarda está puesta, no un defecto.
  /Blocked script execution in 'about:srcdoc'/i,
]

/** `run_id` tal como el panel lo publica: 32 hex. */
const RUN_ID = /run_id\s*([0-9a-f]{32})/i

/** Hosts a los que la interfaz PUEDE hablar. Es un producto que promete no salir a la red. */
const HOSTS_PERMITIDOS = new Set(["127.0.0.1"])

function esRuido(mensaje: ConsoleMessage): boolean {
  return RUIDO_TOLERADO.some((patron) => patron.test(mensaje.text()))
}

test.describe("interfaz servida por el wheel instalado", () => {
  let erroresDeConsola: string[]
  let respuestasFallidas: string[]
  let peticionesFueraDeLoopback: string[]

  test.beforeEach(({ page }) => {
    erroresDeConsola = []
    respuestasFallidas = []
    peticionesFueraDeLoopback = []

    page.on("console", (mensaje: ConsoleMessage) => {
      if (mensaje.type() === "error" && !esRuido(mensaje)) {
        erroresDeConsola.push(mensaje.text())
      }
    })
    page.on("pageerror", (error: Error) => {
      erroresDeConsola.push(`pageerror: ${error.message}`)
    })
    page.on("request", (peticion: Request) => {
      const host = new URL(peticion.url()).hostname
      if (!HOSTS_PERMITIDOS.has(host)) {
        peticionesFueraDeLoopback.push(peticion.url())
      }
    })
    page.on("response", (respuesta: Response) => {
      if (respuesta.status() >= 400) {
        respuestasFallidas.push(`${respuesta.status()} ${respuesta.url()}`)
      }
    })
  })

  test("la SPA monta de verdad: React ejecuta y pinta el catálogo de trabajos", async ({
    page,
  }) => {
    await page.goto("/")

    // `#root` con hijos es la prueba de que el bundle CORRIÓ. El index servido lo trae vacío: si
    // el JS no ejecuta, la página responde 200 y se ve en blanco — exactamente el fallo que un
    // gate por bytes no puede distinguir de un éxito.
    const root = page.locator("#root")
    await expect(root).toBeAttached()
    await expect(root.locator("> *")).not.toHaveCount(0)

    // Contenido que sólo existe si React renderizó el catálogo (SDD «UI por trabajos»).
    await expect(page.getByRole("button", { name: /Scorecard de comportamiento/ }).first()).toBeVisible()

    expect(erroresDeConsola, "la consola del navegador no debe traer errores").toEqual([])
    expect(respuestasFallidas, "ningún asset del bundle puede faltar").toEqual([])
  })

  test("la interfaz no habla con ningún host fuera de loopback", async ({ page }) => {
    await page.goto("/")
    await expect(page.locator("#root > *").first()).toBeVisible()
    expect(
      peticionesFueraDeLoopback,
      "el producto promete que los datos no salen de la máquina",
    ).toEqual([])
  })

  test("recorrido completo: ejemplo → ejecutar → resultados → informe", async ({ page }) => {
    await page.goto("/")

    // Elegir el ejemplo listo salta al paso «Ejecutar» con su config y su dataset cargados. Es el
    // último botón con ese nombre: el primero es la ficha del TRABAJO, que pide traer datos.
    await page
      .getByRole("button", { name: /^Scorecard de comportamiento/ })
      .last()
      .click()

    // ⚠️ Un servidor recién arrancado no tiene corridas, pero el arnés NO puede depender de eso:
    // contra una instancia que ya corrió algo, esperar el texto «Corrida completada» lo satisface
    // el panel de la corrida ANTERIOR y el test pasa en segundos sin haber ejecutado nada. Medido:
    // así se comportaba esta prueba antes de exigir un `run_id` distinto del previo.
    const previo = (await page.locator("main").innerText()).match(RUN_ID)?.[1] ?? null

    const ejecutar = page.getByRole("button", { name: "Ejecutar corrida" })
    await expect(ejecutar).toBeEnabled()
    await ejecutar.click()

    // El scorecard completo tarda: binning, selección, logística, calibración e informe.
    await expect(page.locator("main")).toContainText("Corrida completada", {
      timeout: 10 * 60 * 1000,
    })
    await expect
      .poll(
        async () => (await page.locator("main").innerText()).match(RUN_ID)?.[1] ?? null,
        { message: "el panel debe publicar un run_id nuevo, no el de una corrida anterior" },
      )
      .not.toBe(previo)

    // La corrida tiene que haber terminado BIEN, no sólo haber terminado: la procedencia de la
    // corrida es lo que distingue un resultado publicable de una pantalla que dice «listo».
    await page.getByRole("button", { name: "Ver resultados" }).click()
    await expect(page.getByRole("heading", { name: "Resultados" })).toBeVisible()
    await expect(page.locator("main")).toContainText("run_id")
    await expect(page.locator("main")).toContainText("config_hash")
    await expect(page.locator("main")).toContainText("data_hash")

    // Y el entregable: el informe de esa corrida, servido y RENDERIZADO por el mismo wheel. El
    // visor es un iframe; que exista el botón de descarga no prueba que el informe se produzca.
    await page.locator('nav[aria-label="Secciones"]').getByRole("button", { name: "Reporte" }).click()
    await expect(page.getByRole("heading", { name: "Reporte" })).toBeVisible()
    await expect(page.getByRole("button", { name: "Descargar HTML" })).toBeVisible()

    const visor = page.frameLocator("main iframe")
    await expect(visor.locator("body")).toContainText(/Informe/i, { timeout: 2 * 60 * 1000 })

    expect(erroresDeConsola, "el recorrido no debe ensuciar la consola").toEqual([])
    expect(respuestasFallidas, "ninguna llamada del recorrido puede fallar").toEqual([])
  })
})
