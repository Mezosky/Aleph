/**
 * Optional live-analysis client.
 *
 * The published site is fully static: it renders precomputed bundles from
 * `public/data/`. When `VITE_ALEPH_API_URL` is set at build time the Analyze
 * page can additionally submit a document to a running Aleph API and watch the
 * seven warm phases progress. When it is not set, `isApiConfigured()` returns
 * false and the page must say plainly that live analysis is unavailable in this
 * deployment — an unconfigured build is not a broken build.
 *
 * SECURITY NOTE — read before adding anything here.
 * Everything under `VITE_*` is inlined into the public JavaScript bundle and is
 * readable by anyone who loads the page. This module therefore never reads,
 * stores or transmits an API key, token or credential, and no such variable may
 * be introduced. An API that needs authentication must terminate that
 * authentication server-side; the browser only ever sends the document.
 */

import type { AnalysisBundle, PhaseState, Timestamp, UnitInterval, WarmPhase } from '@/types/aleph'
import { WARM_PHASES } from '@/types/aleph'

/* ------------------------------------------------------------------ *
 * Configuration
 * ------------------------------------------------------------------ */

function normaliseBase(raw: string | undefined): string | null {
  const value = (raw ?? '').trim()
  if (!value) return null
  return value.replace(/\/+$/, '')
}

const API_BASE = normaliseBase(import.meta.env.VITE_ALEPH_API_URL)

/** Whether this build was pointed at a live Aleph API. */
export function isApiConfigured(): boolean {
  return API_BASE !== null
}

/** The configured API origin, or null on a purely static deployment. */
export function apiBaseUrl(): string | null {
  return API_BASE
}

/* ------------------------------------------------------------------ *
 * Errors
 * ------------------------------------------------------------------ */

/** Thrown when a live-analysis call is attempted on a static deployment. */
export class ApiNotConfiguredError extends Error {
  constructor() {
    super(
      'Esta versión del sitio no está conectada a un servicio de análisis. Sólo se muestran análisis ya calculados.',
    )
    this.name = 'ApiNotConfiguredError'
  }
}

export class ApiError extends Error {
  readonly status: number | undefined
  readonly url: string
  readonly detail: string | undefined

  constructor(message: string, url: string, status?: number, detail?: string, cause?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.url = url
    this.status = status
    this.detail = detail
    if (cause !== undefined) {
      Object.defineProperty(this, 'cause', { value: cause, enumerable: false })
    }
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

export function isApiNotConfiguredError(error: unknown): error is ApiNotConfiguredError {
  return error instanceof ApiNotConfiguredError
}

/* ------------------------------------------------------------------ *
 * Job and phase status
 * ------------------------------------------------------------------ */

export type JobState = 'queued' | 'running' | 'complete' | 'failed' | 'cancelled'

/** Progress of one of the seven fixed warm phases. */
export interface PhaseProgress {
  phase: WarmPhase
  state: PhaseState
  started_at?: Timestamp | null
  completed_at?: Timestamp | null
  /** How many items the phase produced, e.g. propositions or evidence records. */
  item_count?: number | null
  note?: string | null
}

/**
 * Status of one submitted analysis. `phases` always contains all seven warm
 * phases, in execution order — a phase that has not reported is shown as
 * `not_started` rather than omitted, so a stalled stage is visible instead of
 * silently missing.
 */
export interface AnalysisStatus {
  id: string
  state: JobState
  /** Overall progress in [0,1], derived from the phases when the API omits it. */
  progress: UnitInterval
  current_phase: WarmPhase | null
  phases: PhaseProgress[]
  message?: string | null
  error?: string | null
  /** Slug of the finished bundle, when the job produced one. */
  slug?: string | null
  created_at?: Timestamp | null
  updated_at?: Timestamp | null
}

export interface SubmitAnalysisInput {
  /** An uploaded document. Mutually exclusive with `url`. */
  file?: File
  /** A public URL for the API to retrieve. Mutually exclusive with `file`. */
  url?: string
  /** Optional human title, used when the document carries none. */
  title?: string
}

export interface SubmitAnalysisResponse {
  id: string
  state: JobState
  /** Absolute or relative status URL, when the API supplies one. */
  status_url?: string | null
}

export interface RequestOptions {
  signal?: AbortSignal
}

/* ------------------------------------------------------------------ *
 * Transport
 * ------------------------------------------------------------------ */

function endpoint(path: string): string {
  if (API_BASE === null) throw new ApiNotConfiguredError()
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === 'AbortError'
    : error instanceof Error && error.name === 'AbortError'
}

async function readProblem(response: Response): Promise<string | undefined> {
  try {
    const text = await response.text()
    if (!text) return undefined
    try {
      const parsed: unknown = JSON.parse(text)
      if (parsed && typeof parsed === 'object') {
        const record = parsed as Record<string, unknown>
        const detail = record.detail ?? record.message ?? record.error
        if (typeof detail === 'string') return detail
      }
    } catch {
      /* Not JSON — fall through to the raw body. */
    }
    return text.slice(0, 400)
  } catch {
    return undefined
  }
}

interface RequestSpec {
  method: 'GET' | 'POST'
  body?: BodyInit
  /** Plain header map only — never a credential. */
  headers?: Record<string, string>
  signal?: AbortSignal
}

async function request<T>(url: string, spec: RequestSpec): Promise<T> {
  const init: RequestInit = {
    method: spec.method,
    headers: { Accept: 'application/json', ...(spec.headers ?? {}) },
  }
  if (spec.body !== undefined) init.body = spec.body
  if (spec.signal) init.signal = spec.signal

  let response: Response
  try {
    response = await fetch(url, init)
  } catch (cause) {
    if (isAbort(cause)) throw cause
    throw new ApiError(
      'No se pudo contactar el servicio de análisis. Puede estar detenido o inalcanzable desde tu red.',
      url,
      undefined,
      undefined,
      cause,
    )
  }

  if (!response.ok) {
    const detail = await readProblem(response)
    const message =
      response.status === 404
        ? 'El servicio de análisis no reconoce ese identificador.'
        : response.status === 413
          ? 'El documento excede el tamaño que acepta el servicio de análisis.'
          : response.status >= 500
            ? 'El servicio de análisis falló al procesar la solicitud.'
            : `El servicio de análisis rechazó la solicitud (${response.status}).`
    throw new ApiError(message, url, response.status, detail)
  }

  try {
    return (await response.json()) as T
  } catch (cause) {
    throw new ApiError(
      'El servicio de análisis respondió con un cuerpo que no es JSON válido.',
      url,
      response.status,
      undefined,
      cause,
    )
  }
}

/* ------------------------------------------------------------------ *
 * Normalisation
 * ------------------------------------------------------------------ */

const JOB_STATES: readonly JobState[] = ['queued', 'running', 'complete', 'failed', 'cancelled']
const PHASE_STATES: readonly PhaseState[] = [
  'not_started',
  'running',
  'complete',
  'failed',
  'skipped',
]

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function asJobState(value: unknown): JobState {
  return typeof value === 'string' && (JOB_STATES as readonly string[]).includes(value)
    ? (value as JobState)
    : 'queued'
}

function asPhaseState(value: unknown): PhaseState {
  return typeof value === 'string' && (PHASE_STATES as readonly string[]).includes(value)
    ? (value as PhaseState)
    : 'not_started'
}

function asWarmPhase(value: unknown): WarmPhase | null {
  return typeof value === 'string' && (WARM_PHASES as readonly string[]).includes(value)
    ? (value as WarmPhase)
    : null
}

function optionalString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null
}

function optionalNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/**
 * Project whatever the API returned onto the fixed seven-phase shape. Phases
 * the API did not mention appear as `not_started`; a phase it invented is
 * dropped, because the seven are a contract and not a suggestion.
 */
function normaliseStatus(raw: unknown, fallbackId: string): AnalysisStatus {
  const record = asRecord(raw)
  const reported = new Map<WarmPhase, PhaseProgress>()

  const rawPhases = record.phases
  if (Array.isArray(rawPhases)) {
    for (const item of rawPhases) {
      const entry = asRecord(item)
      const phase = asWarmPhase(entry.phase)
      if (!phase) continue
      reported.set(phase, {
        phase,
        state: asPhaseState(entry.state),
        started_at: optionalString(entry.started_at),
        completed_at: optionalString(entry.completed_at),
        item_count: optionalNumber(entry.item_count),
        note: optionalString(entry.note),
      })
    }
  } else if (rawPhases && typeof rawPhases === 'object') {
    // Tolerate a map keyed by phase name.
    for (const [key, value] of Object.entries(rawPhases as Record<string, unknown>)) {
      const phase = asWarmPhase(key)
      if (!phase) continue
      const entry = asRecord(value)
      reported.set(phase, {
        phase,
        state: asPhaseState(typeof value === 'string' ? value : entry.state),
        started_at: optionalString(entry.started_at),
        completed_at: optionalString(entry.completed_at),
        item_count: optionalNumber(entry.item_count),
        note: optionalString(entry.note),
      })
    }
  }

  const phases: PhaseProgress[] = WARM_PHASES.map(
    (phase) => reported.get(phase) ?? { phase, state: 'not_started' },
  )

  const completed = phases.filter((p) => p.state === 'complete' || p.state === 'skipped').length
  const reportedProgress = optionalNumber(record.progress)
  const progress =
    reportedProgress !== null
      ? Math.min(1, Math.max(0, reportedProgress > 1 ? reportedProgress / 100 : reportedProgress))
      : completed / WARM_PHASES.length

  const state = asJobState(record.state ?? record.status)
  const running = phases.find((p) => p.state === 'running')

  return {
    id: optionalString(record.id) ?? fallbackId,
    state,
    progress: state === 'complete' ? 1 : progress,
    current_phase: asWarmPhase(record.current_phase) ?? running?.phase ?? null,
    phases,
    message: optionalString(record.message),
    error: optionalString(record.error),
    slug: optionalString(record.slug),
    created_at: optionalString(record.created_at),
    updated_at: optionalString(record.updated_at),
  }
}

/* ------------------------------------------------------------------ *
 * Endpoints
 * ------------------------------------------------------------------ */

/**
 * Submit a document for analysis: either an uploaded file or a public URL.
 * Rejects with `ApiNotConfiguredError` when this build has no API configured.
 */
export async function submitAnalysis(
  input: SubmitAnalysisInput,
  options: RequestOptions = {},
): Promise<SubmitAnalysisResponse> {
  if (API_BASE === null) throw new ApiNotConfiguredError()
  if (!input.file && !input.url?.trim()) {
    throw new ApiError('Indica un archivo o una dirección web para analizar.', endpoint('/v1/analyses'))
  }
  if (input.file && input.url?.trim()) {
    throw new ApiError(
      'Envía un archivo o una dirección web, no ambos.',
      endpoint('/v1/analyses'),
    )
  }

  const url = endpoint('/v1/analyses')
  const spec: RequestSpec = { method: 'POST' }
  if (options.signal) spec.signal = options.signal

  if (input.file) {
    const form = new FormData()
    form.append('file', input.file, input.file.name)
    if (input.title?.trim()) form.append('title', input.title.trim())
    spec.body = form
    // Content-Type is intentionally unset: the browser adds the multipart boundary.
  } else {
    spec.headers = { 'Content-Type': 'application/json' }
    spec.body = JSON.stringify({
      url: input.url?.trim(),
      ...(input.title?.trim() ? { title: input.title.trim() } : {}),
    })
  }

  const raw = await request<unknown>(url, spec)
  const record = asRecord(raw)
  const id = optionalString(record.id) ?? optionalString(record.job_id)
  if (!id) {
    throw new ApiError('El servicio aceptó el documento pero no devolvió un identificador.', url)
  }
  return {
    id,
    state: asJobState(record.state ?? record.status),
    status_url: optionalString(record.status_url),
  }
}

/** Current status of a submitted analysis, with all seven phases present. */
export async function getAnalysisStatus(
  id: string,
  options: RequestOptions = {},
): Promise<AnalysisStatus> {
  if (API_BASE === null) throw new ApiNotConfiguredError()
  const spec: RequestSpec = { method: 'GET' }
  if (options.signal) spec.signal = options.signal
  const raw = await request<unknown>(endpoint(`/v1/analyses/${encodeURIComponent(id)}/status`), spec)
  return normaliseStatus(raw, id)
}

/** The finished bundle for a submitted analysis. */
export async function getAnalysis(
  id: string,
  options: RequestOptions = {},
): Promise<AnalysisBundle> {
  if (API_BASE === null) throw new ApiNotConfiguredError()
  const spec: RequestSpec = { method: 'GET' }
  if (options.signal) spec.signal = options.signal
  return request<AnalysisBundle>(endpoint(`/v1/analyses/${encodeURIComponent(id)}`), spec)
}

/* ------------------------------------------------------------------ *
 * Polling
 * ------------------------------------------------------------------ */

export interface PollOptions extends RequestOptions {
  /** Delay between polls, in milliseconds. Default 2000. */
  intervalMs?: number
  /** Give up after this many milliseconds. Default 15 minutes. */
  timeoutMs?: number
  /** Consecutive transport failures tolerated before giving up. Default 4. */
  maxConsecutiveErrors?: number
}

export interface PollHandle {
  /** Stop polling. `done` then rejects with an AbortError. */
  stop: () => void
  /** Resolves with the terminal status, or rejects on failure or abort. */
  done: Promise<AnalysisStatus>
}

const TERMINAL_STATES: readonly JobState[] = ['complete', 'failed', 'cancelled']

function isTerminal(state: JobState): boolean {
  return TERMINAL_STATES.includes(state)
}

/**
 * Poll a job until it reaches a terminal state, calling `onTick` with every
 * status received. Transient transport failures are tolerated a few times so a
 * momentary blip does not present itself to the reader as a failed analysis.
 */
export function pollStatus(
  id: string,
  onTick: (status: AnalysisStatus) => void,
  options: PollOptions = {},
): PollHandle {
  const intervalMs = options.intervalMs ?? 2000
  const timeoutMs = options.timeoutMs ?? 15 * 60 * 1000
  const maxConsecutiveErrors = options.maxConsecutiveErrors ?? 4

  const controller = new AbortController()
  const stop = () => controller.abort()
  if (options.signal) {
    if (options.signal.aborted) controller.abort()
    else options.signal.addEventListener('abort', stop, { once: true })
  }

  const done = (async (): Promise<AnalysisStatus> => {
    if (API_BASE === null) throw new ApiNotConfiguredError()
    const startedAt = Date.now()
    let consecutiveErrors = 0

    for (;;) {
      if (controller.signal.aborted) throw new DOMException('Seguimiento cancelado.', 'AbortError')

      try {
        const status = await getAnalysisStatus(id, { signal: controller.signal })
        consecutiveErrors = 0
        onTick(status)
        if (isTerminal(status.state)) return status
      } catch (error) {
        if (isAbort(error) || isApiNotConfiguredError(error)) throw error
        consecutiveErrors += 1
        if (consecutiveErrors >= maxConsecutiveErrors) throw error
      }

      if (Date.now() - startedAt > timeoutMs) {
        throw new ApiError(
          'El análisis está tardando más de lo previsto. Puedes volver a consultarlo con su identificador.',
          endpoint(`/v1/analyses/${encodeURIComponent(id)}/status`),
        )
      }

      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => {
          controller.signal.removeEventListener('abort', onAbort)
          resolve()
        }, intervalMs)
        const onAbort = () => {
          clearTimeout(timer)
          reject(new DOMException('Seguimiento cancelado.', 'AbortError'))
        }
        controller.signal.addEventListener('abort', onAbort, { once: true })
      })
    }
  })()

  return { stop, done }
}
