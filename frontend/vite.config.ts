import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { rmSync } from 'node:fs'
import { resolve } from 'node:path'

function pruneLegacyDemoData() {
  return {
    name: 'prune-legacy-demo-data',
    closeBundle() {
      // Generic synthetic fixtures remain available to tests, but the public
      // single-dossier build must not publish them as parallel analyses.
      for (const path of ['data/index.json', 'data/claims', 'data/evidence', 'data/news', 'data/reforms']) {
        rmSync(resolve('dist', path), { recursive: true, force: true })
      }
    },
  }
}

/**
 * The site is published at https://mezosky.github.io/Aleph/, so every asset and
 * data URL has to be resolved against the `/Aleph/` sub-path rather than the
 * domain root. `VITE_BASE` lets a different deployment target (a custom domain,
 * a preview host, a local `vite preview`) override it without a code change.
 *
 * Nothing secret may be referenced here: everything under `VITE_*` is compiled
 * into public JavaScript.
 */
export default defineConfig(({ mode }) => ({
  base: process.env.VITE_BASE ?? '/Aleph/',
  plugins: [react(), pruneLegacyDemoData()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: mode !== 'production',
    // The analysis bundles are large, deeply nested JSON. Splitting the chart
    // library out keeps the initial route light on slow connections.
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/recharts')) return 'charts'
          if (
            id.includes('node_modules/react/') ||
            id.includes('node_modules/react-dom/') ||
            id.includes('node_modules/react-router')
          ) {
            return 'react'
          }
          return undefined
        },
      },
    },
  },
  server: {
    port: 5173,
    host: true,
  },
}))
