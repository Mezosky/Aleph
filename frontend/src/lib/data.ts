/**
 * Static dataset loader.
 *
 * The site is published under a sub-path (`/Aleph/`), so every dataset URL is
 * resolved against `import.meta.env.BASE_URL`. A leading-slash absolute path
 * would 404 on GitHub Pages and is never used here.
 *
 * Failure is a first-class outcome. A fetch that fails rejects with a
 * `DataError` carrying a message written for a reader, so a page can render
 * "no pudimos cargar el análisis" instead of an empty screen that looks like an
 * absence of findings — which, in a product about evidence, would be the worst
 * possible failure mode.
 */

import type {
  AnalysisBundle,
  ClaimSet,
  Claim,
  EvidencePool,
  EvidenceItem,
  NewsFeed,
  Proposition,
  SiteIndex,
} from '@/types/aleph'
import type { MegareformaDossier, MegareformaSources } from '@/types/megareforma'

/* ------------------------------------------------------------------ *
 * URLs
 * ------------------------------------------------------------------ */

/**
 * Resolve a path inside `public/data/` against the deployed base path.
 * `dataUrl('reforms/18216-05.json')` → `/Aleph/data/reforms/18216-05.json`.
 */
export function dataUrl(path: string): string {
  const base = import.meta.env.BASE_URL || '/'
  const prefix = base.endsWith('/') ? base : `${base}/`
  return `${prefix}data/${path.replace(/^\/+/, '')}`
}

/** Static data paths, in one place so a rename cannot drift between callers. */
export const DATA_PATHS = {
  siteIndex: 'index.json',
  analysis: (slug: string) => `reforms/${slug}.json`,
  claims: (slug: string) => `claims/${slug}.json`,
  evidence: (slug: string) => `evidence/${slug}.json`,
  latestNews: 'news/latest.json',
  megareformaDossier: 'megareforma/dossier.json',
  megareformaSources: 'megareforma/sources.json',
} as const

/* ------------------------------------------------------------------ *
 * Errors
 * ------------------------------------------------------------------ */

export type DataErrorKind = 'network' | 'not_found' | 'http' | 'parse'

/**
 * A dataset that could not be loaded. `message` is Spanish UI copy: it is meant
 * to be rendered, not logged and swallowed.
 */
export class DataError extends Error {
  readonly kind: DataErrorKind
  readonly url: string
  readonly status: number | undefined

  constructor(kind: DataErrorKind, message: string, url: string, status?: number, cause?: unknown) {
    super(message)
    this.name = 'DataError'
    this.kind = kind
    this.url = url
    this.status = status
    if (cause !== undefined) {
      // `cause` is standard on Error but not in the ES2022 lib target used here.
      Object.defineProperty(this, 'cause', { value: cause, enumerable: false })
    }
  }
}

export function isDataError(error: unknown): error is DataError {
  return error instanceof DataError
}

/** True when a rejection came from an aborted request rather than a real failure. */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === 'AbortError'
    : error instanceof Error && error.name === 'AbortError'
}

/** Reader-facing description of a failure, for an error panel. */
export function describeDataError(error: unknown): string {
  if (isDataError(error)) return error.message
  if (error instanceof Error && error.message) return error.message
  return 'Ocurrió un error inesperado al cargar los datos.'
}

/* ------------------------------------------------------------------ *
 * Fetch + cache
 * ------------------------------------------------------------------ */

const cache = new Map<string, unknown>()

interface PendingRequest {
  promise: Promise<unknown>
  controller: AbortController
  /** Callers still waiting. The shared fetch is aborted only when this hits 0. */
  waiters: number
}

const pending = new Map<string, PendingRequest>()

async function fetchJson(url: string, signal: AbortSignal): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(url, {
      signal,
      headers: { Accept: 'application/json' },
    })
  } catch (cause) {
    if (isAbortError(cause)) throw cause
    throw new DataError(
      'network',
      'No se pudo contactar el origen de datos. Revisa tu conexión e inténtalo de nuevo.',
      url,
      undefined,
      cause,
    )
  }

  if (!response.ok) {
    const kind: DataErrorKind = response.status === 404 ? 'not_found' : 'http'
    const message =
      response.status === 404
        ? 'No existe un conjunto de datos en esa dirección.'
        : `El origen de datos respondió con un error (${response.status}).`
    throw new DataError(kind, message, url, response.status)
  }

  try {
    return (await response.json()) as unknown
  } catch (cause) {
    throw new DataError(
      'parse',
      'El archivo de datos existe pero no es JSON válido. El conjunto está corrupto o incompleto.',
      url,
      response.status,
      cause,
    )
  }
}

function abortError(): DOMException {
  return new DOMException('La carga fue cancelada.', 'AbortError')
}

/**
 * Load and memoise one JSON document.
 *
 * Concurrent callers share a single request. Each caller may abort
 * independently: only the caller that aborted rejects, and the underlying fetch
 * is cancelled only once every waiter has gone away. Aborting a route
 * transition therefore never poisons a load another component still wants.
 */
async function loadJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  if (cache.has(url)) return cache.get(url) as T
  if (signal?.aborted) throw abortError()

  let entry = pending.get(url)
  if (!entry) {
    const controller = new AbortController()
    const created: PendingRequest = {
      controller,
      waiters: 0,
      promise: Promise.resolve(),
    }
    created.promise = fetchJson(url, controller.signal).then(
      (value) => {
        cache.set(url, value)
        pending.delete(url)
        return value
      },
      (error: unknown) => {
        pending.delete(url)
        throw error
      },
    )
    pending.set(url, created)
    entry = created
  }

  const shared = entry
  shared.waiters += 1

  const release = () => {
    shared.waiters -= 1
    if (shared.waiters <= 0 && pending.get(url) === shared) {
      pending.delete(url)
      shared.controller.abort()
    }
  }

  try {
    if (!signal) return (await shared.promise) as T
    return await new Promise<T>((resolve, reject) => {
      const onAbort = () => reject(abortError())
      signal.addEventListener('abort', onAbort, { once: true })
      shared.promise.then(
        (value) => {
          signal.removeEventListener('abort', onAbort)
          resolve(value as T)
        },
        (error: unknown) => {
          signal.removeEventListener('abort', onAbort)
          reject(error)
        },
      )
    })
  } finally {
    release()
  }
}

/** Drop every memoised dataset. Used by the refresh affordance and by tests. */
export function clearDataCache(): void {
  cache.clear()
}

/** Whether a dataset is already in memory, so a view can skip its skeleton. */
export function isCached(path: string): boolean {
  return cache.has(dataUrl(path))
}

/* ------------------------------------------------------------------ *
 * Typed loaders
 * ------------------------------------------------------------------ */

/** The site manifest: which analyses exist and which one is featured. */
export async function loadSiteIndex(signal?: AbortSignal): Promise<SiteIndex> {
  const url = dataUrl(DATA_PATHS.siteIndex)
  const value = await loadJson<SiteIndex>(url, signal)
  if (!value || !Array.isArray(value.analyses)) {
    throw new DataError('parse', 'El índice del sitio no tiene la forma esperada: falta la lista de análisis.', url)
  }
  return value
}

/** Frozen, canonical dossier used by the single-document GitHub Pages build. */
export async function loadMegareformaDossier(signal?: AbortSignal): Promise<MegareformaDossier> {
  const url = dataUrl(DATA_PATHS.megareformaDossier)
  const value = await loadJson<MegareformaDossier>(url, signal)
  if (!value || value.data_status !== 'real_frozen_snapshot' || !Array.isArray(value.objectives)) {
    throw new DataError('parse', 'El dossier congelado no tiene la forma esperada.', url)
  }
  return value
}

/** Captured original-source cards, including screenshots and stated retrieval gaps. */
export async function loadMegareformaSources(signal?: AbortSignal): Promise<MegareformaSources> {
  const url = dataUrl(DATA_PATHS.megareformaSources)
  const value = await loadJson<MegareformaSources>(url, signal)
  if (!value || !Array.isArray(value.items) || !Array.isArray(value.gaps)) {
    throw new DataError('parse', 'El registro de fuentes no tiene la forma esperada.', url)
  }
  return value
}

/** One document's complete analysis bundle. */
export async function loadAnalysis(slug: string, signal?: AbortSignal): Promise<AnalysisBundle> {
  const safe = slug.trim()
  if (!safe || !/^[a-z0-9][a-z0-9._-]*$/i.test(safe)) {
    throw new DataError('not_found', 'El identificador del documento no es válido.', dataUrl('reforms/'))
  }
  const url = dataUrl(DATA_PATHS.analysis(safe))
  const value = await loadJson<AnalysisBundle>(url, signal)
  if (!value || !value.document || !value.readiness) {
    throw new DataError(
      'parse',
      'El análisis existe pero está incompleto: falta el documento o el informe de suficiencia de evidencia.',
      url,
    )
  }
  return value
}

/** The cross-analysis news feed with its per-article summary metrics. */
export async function loadLatestNews(signal?: AbortSignal): Promise<NewsFeed> {
  const url = dataUrl(DATA_PATHS.latestNews)
  const value = await loadJson<NewsFeed>(url, signal)
  if (!value || !Array.isArray(value.items)) {
    throw new DataError('parse', 'El listado de cobertura no tiene la forma esperada.', url)
  }
  return value
}

/** The standalone claim set, when a view needs claims without the whole bundle. */
export async function loadClaims(slug: string, signal?: AbortSignal): Promise<ClaimSet> {
  return loadJson<ClaimSet>(dataUrl(DATA_PATHS.claims(slug)), signal)
}

/** The standalone evidence pool. */
export async function loadEvidence(slug: string, signal?: AbortSignal): Promise<EvidencePool> {
  return loadJson<EvidencePool>(dataUrl(DATA_PATHS.evidence(slug)), signal)
}

/* ------------------------------------------------------------------ *
 * Bundle accessors
 *
 * The bundle nests some warm-phase outputs as whole schema documents rather
 * than as bare arrays. These helpers give components one stable shape and
 * tolerate a producer that flattened the field, so a shape mismatch degrades
 * to an empty list rather than to a crash on `undefined.map`.
 * ------------------------------------------------------------------ */

/** The atomic propositions, whether the producer nested them or flattened them. */
export function getPropositions(bundle: Pick<AnalysisBundle, 'propositions'>): Proposition[] {
  const value: unknown = bundle.propositions
  if (Array.isArray(value)) return value as Proposition[]
  if (value && typeof value === 'object') {
    const inner = (value as { propositions?: unknown }).propositions
    if (Array.isArray(inner)) return inner as Proposition[]
  }
  return []
}

/** Index the evidence pool by id, for resolving `evidence_refs`. */
export function indexEvidence(items: readonly EvidenceItem[]): Map<string, EvidenceItem> {
  return new Map(items.map((item) => [item.id, item]))
}

/** Index claims by id, for resolving `claim_id` references. */
export function indexClaims(claims: readonly Claim[]): Map<string, Claim> {
  return new Map(claims.map((claim) => [claim.id, claim]))
}
