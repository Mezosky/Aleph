/**
 * Entry point.
 *
 * The theme is already resolved by the pre-paint script in `index.html`, so
 * nothing here touches `documentElement` before the first frame — see
 * `src/lib/theme.ts` for the shared contract.
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from '@/App'
import '@/styles/index.css'

const container = document.getElementById('root')

if (!container) {
  throw new Error('No se encontró el elemento #root: revisa index.html.')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
