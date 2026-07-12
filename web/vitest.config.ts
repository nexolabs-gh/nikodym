import path from "node:path"

import { defineConfig } from "vitest/config"

// El motor de formulario (`lib/form-engine.ts`, `lib/config-store.ts`) es LÓGICA
// PURA sin React ni DOM: entorno `node` basta. La mayoría de los tests usan imports
// relativos, PERO `report.ts` importa el VALOR `ApiError` (para `instanceof`) desde
// `./api`, que a su vez importa `@/lib/demo` como valor; por eso vitest debe resolver
// el alias `@/` (Vite ya maneja `?raw`/`?url`/`.json` de la cadena de demo por sí solo).
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
})
