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
  actor_ids: string[]
  pole_actor_ids?: { left: string[]; right: string[] }
}

export interface OtherDebateAngle {
  id: string
  title: string
  question: string
  finding: string
  why_it_matters: string
  limitation: string
  source_ids: string[]
  actor_ids: string[]
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
  public_record: ActorPublicRecord[]
  record_caveat: string
  sources: ActorSource[]
}

export interface ActorPublicRecord {
  date: string
  action: string
  outcome: string
  assessment: string
  status: 'observed' | 'pending' | 'not_testable'
  source_ids: string[]
}

export type MunicipalPositionGroup =
  'government_formula' | 'targeted_exemption' | 'revenue_protection' | 'dialogue_participant'

export interface MunicipalActor {
  id: string
  name: string
  municipality: string
  role: string
  affiliation: string
  position_group: MunicipalPositionGroup
  position_summary: string
  public_record: ActorPublicRecord[]
  source_ids: string[]
  record_caveat: string
  image?: string
  image_alt?: string
  image_credit?: string
  image_license?: string
  image_source_url?: string
  image_sha256?: string
}

export interface MunicipalActorIndex {
  schema_version: string
  document_id: '18216-05'
  retrieval_cutoff: string
  coverage: {
    universe: string
    method: string
    municipal_sources_curated: number
    actors_indexed: number
    blind_path_rule: string
    limitation: string
  }
  actors: MunicipalActor[]
}

export interface DeepTopic {
  id: string
  title: string
  group:
    | 'gasto_y_reconstruccion'
    | 'educacion'
    | 'empleo_publico'
    | 'regulacion'
    | 'tributos_permanentes'
    | 'tributos_transitorios'
    | 'efecto_fiscal'
  pages: number[]
  what_changes: string
  mechanism: string
  government_goal: string
  affected_groups: string[]
  fiscal_effect: string
  assumptions: string[]
  risks_and_open_questions: string[]
  source_quote: string
  source_page: number
  quote_verified: true
  news_source_ids: string[]
  coverage_status: 'captured_news' | 'no_captured_news'
}

export interface MegareformaDeepAnalysis {
  schema_version: string
  generated_at: string
  execution: 'local_gpu_offline'
  runtime_calls: 0
  document: {
    id: '18216-05'
    sha256: string
    pages: 46
    paragraphs: number
    propositions: number
    last_structured_page: 46
  }
  coverage: {
    topics_declared: 30
    topics_grounded: 30
    topics_with_captured_news: number
    topics_without_captured_news: number
    pages_structured: 46
    page_coverage_percent: 100
    blank_pages: number[]
    reviewed_model_fields: number
    review_method: string
    methodology: string
    limitation: string
  }
  topics: DeepTopic[]
  model: { name: string; revision: string; batches: number; usage: Record<string, number> }
}

export interface CensusMention {
  source_id: string
  action_or_position: string
  evidence_quote: string
}

export interface CensusActor {
  id: string
  name: string
  entity_kind: 'person' | 'institution'
  actor_type:
    | 'government'
    | 'legislator'
    | 'mayor'
    | 'political_party'
    | 'municipal_association'
    | 'technical_body'
    | 'judiciary'
    | 'business'
    | 'union'
    | 'civil_society'
    | 'academic'
    | 'international_organization'
    | 'other'
  role: string
  institution: string
  affiliation: string
  affiliation_status:
    | 'verified_public_record'
    | 'independent_public_record'
    | 'reported_in_corpus'
    | 'institutional_not_applicable'
    | 'not_documented'
  affiliation_source_url?: string
  affiliation_verified_at?: string
  participation_summary: string
  profile_depth: 'detailed' | 'indexed'
  source_ids: string[]
  mentions: CensusMention[]
  public_record?: ActorPublicRecord[]
  record_caveat?: string
  image?: string
  image_alt?: string
  image_credit?: string
  image_license?: string
  image_source_url?: string
}

export interface ActorCensus {
  schema_version: string
  generated_at: string
  execution: 'local_gpu_offline'
  runtime_calls: 0
  coverage: {
    captured_sources_total: number
    captured_sources_audited: number
    text_chunks_audited: number
    actors_indexed: number
    people: number
    institutions: number
    detailed_profiles: number
    indexed_only: number
    accepted_mentions: number
    rejected_ungrounded_candidates: number
    universe: string
    limitation: string
  }
  actors: CensusActor[]
  model: { name: string; revision: string; batches: number; usage: Record<string, number> }
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
  news_source_ids: string[]
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
  other_angles: OtherDebateAngle[]
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
  kind: 'official_record' | 'news' | 'research'
  format?: 'article' | 'opinion' | 'video' | 'audio' | 'transcript' | 'report' | 'paper'
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

export interface TheoryTopic {
  id:
    | 'corporate_tax_growth'
    | 'fiscal_self_financing'
    | 'environmental_permits'
    | 'housing_property_tax'
    | 'higher_education'
    | 'text_data_mining'
  title: string
  question: string
  bottom_line: string
  findings: string[]
  application_to_reform: string
  limits: string
  source_ids: string[]
}

export interface MegareformaTheory {
  schema_version: string
  generated_at: string
  execution: 'local_gpu_offline'
  runtime_calls: 0
  methodology: string
  topics: TheoryTopic[]
  model: {
    provider: 'qwen'
    name: string
    usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
    structured_output_mode: 'json_schema' | 'json_object' | 'prompt'
  }
}
