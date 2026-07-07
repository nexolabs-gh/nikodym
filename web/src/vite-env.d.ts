/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL del backend FastAPI. Default: http://localhost:8000 */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
