export type MeterKind = 'editorial_tone' | 'policy_tradeoff' | 'public_interest'

export interface MeterEvidence {
  label: string
  value: number
  source_ids: string[]
}

export interface DossierMeter {
  id: string
  kind: MeterKind
  title: string
  question: string
  left_label: string
  center_label: string
  right_label: string
  /** Position on the named axis. Zero is the left pole and 100 the right pole. */
  value: number
  confidence: 'low' | 'medium' | 'high'
  explanation: string
  methodology: string
  evidence: MeterEvidence[]
  pole_actor_ids?: { left: string[]; right: string[] }
}

export interface ReformObjective {
  id: string
  category?: string
  title: string
  plain_language: string
  mechanism: string
  affected_groups: string[]
  source_quote: string
  page: number
  caveat: string
  quote_verified: boolean
}

export interface ActorSource {
  label: string
  url: string
  kind: 'official' | 'wikipedia' | 'wikimedia'
}

export interface ActorProfile {
  id: string
  name: string
  role: string
  institution: string
  affiliation: string
  position_summary: string
  image: string
  image_alt: string
  image_credit: string
  image_license: string
  image_source_url: string
  roles: string[]
  legal_record: []
  sources: ActorSource[]
}

export interface DebatePosition {
  side: 'government' | 'opposition' | 'technical'
  actor_ids: string[]
  claim: string
  source_ids: string[]
}

export interface DebateQuestion {
  id: string
  title: string
  subtitle: string
  positions: DebatePosition[]
  verdict: 'supported' | 'contradicted' | 'mixed' | 'conditional' | 'unresolved'
  verdict_label: string
  assessment: string
  what_would_resolve_it: string
  source_ids: string[]
}

export interface MegareformaDossier {
  schema_version: string
  generated_at: string
  retrieval_cutoff: string
  data_status: 'real_frozen_snapshot'
  document: {
    id: string
    title: string
    short_title: string
    source_url: string
    pdf_url: string
    date: string
    page_count: number
    sha256: string
    scope_note: string
  }
  model: {
    name: string
    revision: string
    execution: 'local_gpu_offline'
    runtime_calls: 0
  }
  summary: string
  objectives: ReformObjective[]
  meters: DossierMeter[]
  debate: DebateQuestion[]
  actors: ActorProfile[]
  counts: {
    propositions: number
    sources_curated: number
    sources_captured: number
    capture_gaps: number
    model_runs_completed: number
  }
}

export interface CapturedSource {
  id: string
  publisher: string
  kind: 'official_record' | 'news'
  perspective: string
  published_at: string
  url: string
  original_url: string
  title: string
  summary: string
  screenshot: string
  screenshot_sha256: string
  captured_at: string
}

export interface SourceGap {
  id: string
  url: string
  error: string
}

export interface MegareformaSources {
  schema_version: string
  document_id: string
  retrieval_cutoff: string
  scrape_run_id: string
  capture_count: number
  gap_count: number
  items: CapturedSource[]
  gaps: SourceGap[]
}
