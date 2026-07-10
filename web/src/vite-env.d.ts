/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL del backend FastAPI. Default: http://localhost:8000 */
  readonly VITE_API_BASE?: string
  /** "true" en el build de la demo estática (fixtures embebidos, sin backend). */
  readonly VITE_DEMO_MODE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
