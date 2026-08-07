import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

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
  plugins: [react()],
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
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
        },
      },
    },
  },
  server: {
    port: 5173,
    host: true,
  },
}))
