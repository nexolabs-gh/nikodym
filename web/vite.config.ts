import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// @ts-expect-error El plugin Node es JavaScript ESM versionado fuera del proyecto TS del SPA.
import { frontendProvenancePlugin } from '../scripts/frontend_provenance_plugin.mjs'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const demo = mode === 'demo'
  const demoOutDir = process.env.NIKODYM_DEMO_OUT_DIR
  return {
    plugins: [
      react(),
      tailwindcss(),
      ...(demo ? [] : [frontendProvenancePlugin()]),
    ],
    build: {
      modulePreload: { polyfill: false },
      outDir: demo
        ? path.resolve(demoOutDir ?? path.resolve(__dirname, './dist'))
        : path.resolve(__dirname, '../src/nikodym/ui/static'),
      emptyOutDir: true,
    },
    resolve: {
      alias: [
        {
          find: '@/lib/demo-runtime',
          replacement: path.resolve(
            __dirname,
            demo ? './src/lib/demo.ts' : './src/lib/demo-disabled.ts',
          ),
        },
        { find: '@', replacement: path.resolve(__dirname, './src') },
      ],
    },
  }
})
