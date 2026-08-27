import { defineConfig, devices } from "@playwright/test"

/**
 * Clean-room de la UI distribuida (B2.4).
 *
 * Este arnés NO levanta el servidor: lo levanta quien lo invoca, desde un venv donde el **wheel
 * candidato** está instalado, fuera del checkout. Es la diferencia con `vitest`, que corre sin DOM
 * y no ejerce el bundle, y con `scripts/smoke_instalacion_pip.py`, que llama a la app in-process
 * con `TestClient` — o sea sin navegador y sin el JS/CSS que el usuario realmente ejecuta.
 *
 * Hasta la 1.11.0 el árbol estático distribuido se verificaba **por bytes** (sha256 contra la
 * procedencia del frontend) y no se ejecutaba nunca: un bundle íntegro pero roto pasaba los 16
 * jobs. Esto lo cierra.
 */
const baseURL = process.env.NIKODYM_UI_URL ?? "http://127.0.0.1:8000"

export default defineConfig({
  testDir: "./e2e",
  // Un recorrido de scorecard completo tarda; el default de 30 s no alcanza y un timeout suelto
  // se lee como fallo de producto en vez de como arnés mal calibrado.
  timeout: 15 * 60 * 1000,
  expect: { timeout: 30 * 1000 },
  // Determinismo por encima de velocidad: son gates de release, no una suite de desarrollo.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL,
    // El bind es fijo a loopback por decisión de seguridad (D-UI-R0) y el `Host` se compara
    // exacto: navegar por `localhost` en vez de `127.0.0.1` devuelve 403 y parecería un bug.
    ignoreHTTPSErrors: false,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
