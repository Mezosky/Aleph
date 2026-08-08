/// <reference types="vite/client" />

/**
 * Typed build-time configuration.
 *
 * Everything declared here is compiled into the public JavaScript bundle, so no
 * value in this interface may ever hold a secret. Model credentials belong to
 * the API's own environment, never to the frontend.
 */
interface ImportMetaEnv {
  /**
   * Base URL for the analysis API. Empty or undefined means no API is
   * configured, in which case the site runs purely from the precomputed static
   * datasets and the "analyse a PDF" flow explains that it is unavailable.
   */
  readonly VITE_ALEPH_API_URL?: string
  /** Public Cloudflare Web Analytics site token. This is not an API credential. */
  readonly VITE_CLOUDFLARE_WEB_ANALYTICS_TOKEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
