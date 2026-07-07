import { defineConfig } from "vitest/config"

// El motor de formulario (`lib/form-engine.ts`, `lib/config-store.ts`) es LÓGICA
// PURA sin React ni DOM: entorno `node` basta. Los tests usan imports relativos,
// así que no se necesita resolver el alias `@/` aquí.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
})
