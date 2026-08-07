/**
 * ALEPH DATA CONTRACT — hand-written TypeScript mirror of /schemas/*.json.
 *
 * Key names, enum members and optionality are identical to the JSON Schema
 * files. Where a schema marks a property `required` it is non-optional here;
 * where a schema allows `null` the type includes `| null`. Nothing in this file
 * invents a field, and — deliberately — nothing here aggregates.
 *
 * Three product rules are visible in the shape of these types and must survive
 * any edit:
 *
 *  1. There is no scalar "bias", "leaning" or "political position" anywhere.
 *     The eight framing dimensions and the seven impact axes are separate
 *     numbers with pinned polarity, and no type here can collapse them.
 *  2. A verdict exists only inside `BlindEvaluation`. `Claim` has no top-level
 *     verdict field, so no attributed pass can overwrite one.
 *  3. Every score type travels with `components[]` and a `Confidence`, because
 *     a number a reader cannot open is an assertion rather than an analysis.
 *
 * `analysis_bundle.json` is the frontend contract: `AnalysisBundle` below is
 * the exact shape of `public/data/reforms/<slug>.json`.
 */

/** Version of the data contract this frontend is written against. */
export const ALEPH_SCHEMA_VERSION = '1.0.0'

/* ================================================================== *
 * common.json — shared primitives and controlled vocabularies
 * ================================================================== */

/** Semantic version string, e.g. `"1.0.0"`. */
export type SchemaVersion = string

/** Timezone-aware UTC instant, ISO-8601, e.g. `"2026-08-07T14:03:00Z"`. */
export type Timestamp = string

/** Calendar date, ISO-8601, e.g. `"2026-08-07"`. */
export type DateString = string

/** A value in [0,1]. */
export type UnitInterval = number

/** A 0–100 score. Never interpret without the accompanying polarity. */
export type Score100 = number

/** A −100..+100 position on a named two-poled axis. Not a party label. */
export type BipolarScore = number

/** Stable, human-readable, prefixed identifier (`doc:`, `prov:`, `clm:`, …). */
export type AlephId = string

export type DataStatus = 'synthetic' | 'derived' | 'partial' | 'stale'

export type Polarity = 'higher_is_better' | 'lower_is_better' | 'neutral'

export type StatementType = 'fact' | 'interpretation' | 'forecast' | 'opinion' | 'normative'

export type Verdict =
  | 'supported'
  | 'partially_supported'
  | 'unsupported'
  | 'contradicted'
  | 'unverifiable'
  | 'not_a_factual_claim'
  | 'forecast_conditional'

export type EvidenceStrength = 'high' | 'medium' | 'low' | 'insufficient'

export type EvidenceTier =
  | 'primary_document'
  | 'legislative_record'
  | 'official_technical_report'
  | 'statistical_dataset'
  | 'peer_reviewed'
  | 'expert_analysis'
  | 'journalism'
  | 'political_statement'
  | 'social_media'

export type Direction = 'positive' | 'negative' | 'mixed' | 'uncertain' | 'none'

export type Magnitude = 'small' | 'medium' | 'large' | 'unknown'

export type TimeHorizon = 'immediate' | 'short_term' | 'medium_term' | 'long_term' | 'unknown'

export type Causality = 'direct' | 'indirect' | 'unknown'

export type ReadinessState = 'insufficient' | 'partial' | 'ready'

export type Independence =
  | 'original_reporting'
  | 'syndicated'
  | 'derivative'
  | 'aggregated'
  | 'unknown'

export type WarmPhase =
  | 'document_understanding'
  | 'proposition_extraction'
  | 'topic_graph'
  | 'search_vocabulary'
  | 'evidence_collection'
  | 'news_clustering'
  | 'readiness'

export type MoneyUnit = 'unit' | 'thousand' | 'million' | 'billion' | 'percent_of_gdp'

export type QuantityKind =
  | 'percentage'
  | 'percentage_point'
  | 'count'
  | 'ratio'
  | 'index'
  | 'rate'
  | 'duration'
  | 'other'

export type SourceKind = 'document' | 'article' | 'dataset' | 'webpage' | 'statement' | 'derived'

export type ConfidenceFactor =
  | 'primary_source_coverage'
  | 'evidence_agreement'
  | 'temporal_consistency'
  | 'quantitative_validation'
  | 'source_independence'
  | 'retrieval_completeness'
  | 'claim_ambiguity'

export type ConfidenceEffect = 'raises' | 'lowers' | 'neutral'

export type UncertaintyKind =
  | 'missing_evidence'
  | 'conflicting_evidence'
  | 'model_dependency'
  | 'definitional_ambiguity'
  | 'temporal'
  | 'measurement'
  | 'out_of_scope'

/**
 * A monetary amount. Aleph never stores a bare number for money: currency,
 * scale multiplier and reference year are what make a figure checkable.
 */
export interface Money {
  amount: number
  /** ISO-4217 code where one exists. */
  currency: string
  unit: MoneyUnit
  /** Reference year for real/constant terms. Null when the source states none. */
  year?: number | null
  /** e.g. `nominal`, `constant`, `annual`, `cumulative_10y`. */
  basis?: string | null
}

/** A non-monetary numeric value, with the literal source text preserved. */
export interface Quantity {
  value: number
  kind: QuantityKind
  unit?: string | null
  /** Verbatim substring from the source, before normalisation. */
  raw_text: string
}

/** A located region of a source document, with the verbatim passage. */
export interface Span {
  page?: number | null
  section_id?: string | null
  char_start?: number | null
  char_end?: number | null
  /** The exact supporting passage. An assertion with no quotable text is not traceable. */
  text: string
}

/** Where an extracted item came from. Withheld from the blind evaluator. */
export interface Provenance {
  source_id: AlephId
  source_kind: SourceKind
  url?: string | null
  retrieved_at?: Timestamp | null
  span?: Span | null
  /** Component or model version that produced this item. */
  extractor?: string | null
}

export interface ConfidenceBasis {
  factor: ConfidenceFactor
  effect: ConfidenceEffect
  note?: string
}

/**
 * Evidence confidence and model confidence are separate on purpose. Interfaces
 * MUST surface `evidence_confidence` as the primary figure; a high
 * `model_confidence` over thin evidence is not reassurance.
 */
export interface Confidence {
  evidence_confidence: UnitInterval
  /** Self-reported model confidence. Diagnostic only, never the headline. */
  model_confidence?: UnitInterval | null
  basis?: ConfidenceBasis[]
  /** The single biggest reason confidence is not higher, in plain language. */
  limiting_factor?: string | null
}

/** One inspectable contributor to a composite score. */
export interface Component {
  label: string
  direction: Direction
  /** Signed contribution in the score's own units. */
  weight: number
  evidence_refs?: AlephId[]
  note?: string | null
}

/** A pointer to an external source. There is deliberately no credibility field. */
export interface SourceRef {
  id: AlephId
  title: string
  url?: string | null
  publisher?: string | null
  published_at?: Timestamp | DateString | null
  tier: EvidenceTier
  independence?: Independence
  /** BCP-47 tag, e.g. `es-CL`. */
  language?: string | null
}

/** An explicit statement of what remains unresolved. */
export interface Uncertainty {
  statement: string
  kind: UncertaintyKind
  /** What specific evidence would settle this, if any. */
  resolvable_by?: string | null
}

/* ================================================================== *
 * document.json — DocumentModel (warm phase 1)
 * ================================================================== */

export type JurisdictionLevel =
  | 'supranational'
  | 'national'
  | 'subnational'
  | 'municipal'
  | 'sectoral'
  | 'unknown'

export interface Jurisdiction {
  code?: string | null
  name?: string | null
  level: JurisdictionLevel
}

export interface PageRange {
  start: number
  end: number
}

export interface DocumentIdentifier {
  /** Numbering scheme, e.g. `bill_number`, `gazette`, `doi`. */
  scheme: string
  value: string
  issuer?: string | null
}

export type AuthorshipEntityKind =
  | 'institution'
  | 'committee'
  | 'office'
  | 'working_group'
  | 'individual_role'
  | 'unknown'

/** Responsibility recorded as a ROLE wherever the document permits it. */
export interface AuthorshipEntry {
  role: string
  entity_kind: AuthorshipEntityKind
  entity?: string | null
  /** True only when `entity` holds a named individual. Redaction must strip these. */
  is_personal_name?: boolean
  span?: Span | null
}

export interface DocumentDates {
  introduced?: DateString | null
  published?: DateString | null
  retrieved?: Timestamp | null
  last_amended?: DateString | null
  effective_from?: DateString | null
}

/**
 * Known document kinds. Any other lowercase snake_case string is accepted so an
 * arbitrary PDF passes through; consumers MUST render an unrecognised value as
 * "other" rather than failing.
 */
export type KnownDocumentType =
  | 'bill'
  | 'law'
  | 'decree'
  | 'regulation'
  | 'financial_report'
  | 'technical_report'
  | 'budget'
  | 'ruling'
  | 'consultation'
  | 'other'

export type DocumentType = KnownDocumentType | (string & Record<never, never>)

export type DocumentStatus =
  | 'draft'
  | 'proposed'
  | 'introduced'
  | 'in_committee'
  | 'passed'
  | 'enacted'
  | 'in_force'
  | 'amended'
  | 'suspended'
  | 'repealed'
  | 'superseded'
  | 'withdrawn'
  | 'rejected'
  | 'published'
  | 'unknown'

export interface DocumentIdentity {
  /** URL-safe stable key used in ids and static data paths. */
  slug: string
  /** Official title as printed. Not paraphrased. */
  title: string
  subtitle?: string | null
  short_title?: string | null
  jurisdiction: Jurisdiction
  institution?: string | null
  document_type: DocumentType
  /** The document's own self-description of its type, verbatim. */
  document_type_raw?: string | null
  /** BCP-47 tag, e.g. `es-CL`. */
  language: string
  additional_languages?: string[]
  version?: string | null
  legislative_identifier?: string | null
  identifiers?: DocumentIdentifier[]
  status: DocumentStatus
  dates?: DocumentDates
  authorship?: AuthorshipEntry[]
  summary?: string | null
  keywords?: string[]
}

export type ExtractionQualityState = 'good' | 'degraded' | 'poor' | 'unknown'

export interface ExtractionQuality {
  state: ExtractionQualityState
  /** Fraction of pages from which usable text was recovered. */
  text_coverage?: UnitInterval
  chars_extracted?: number | null
  pages_without_text?: number[]
  ocr_used?: boolean
  ocr_confidence?: UnitInterval | null
  tables_detected?: number | null
  note?: string | null
}

export type RetrievalMethod = 'url_fetch' | 'file_upload' | 'local_path' | 'fixture' | 'unknown'

export type ExtractionMethod =
  | 'pymupdf_text'
  | 'pypdf_text'
  | 'ocr'
  | 'html_dom'
  | 'plain_text'
  | 'manual'
  | 'fixture'
  | 'other'

export type HashAlgorithm = 'sha256' | 'sha512' | 'sha1' | 'md5'

export interface DocumentSource {
  url?: string | null
  file_name?: string | null
  media_type?: string | null
  file_hash?: string | null
  hash_algorithm?: HashAlgorithm | null
  file_size_bytes?: number | null
  page_count?: number | null
  retrieved_at?: Timestamp | null
  retrieval_method?: RetrievalMethod
  extraction_method: ExtractionMethod
  extractor_version?: string | null
  extraction_quality: ExtractionQuality
  license_note?: string | null
}

export type SectionType =
  | 'preamble'
  | 'recital'
  | 'part'
  | 'title'
  | 'chapter'
  | 'article'
  | 'clause'
  | 'paragraph'
  | 'annex'
  | 'schedule'
  | 'table'
  | 'footnote'
  | 'signature_block'
  | 'other'

/** One node of the document outline. Recursive: scope is what a provision applies to. */
export interface Section {
  /** Stable within the document, e.g. `sec:2.1`. Referenced by `Span.section_id`. */
  id: string
  /** The document's own numbering label, verbatim. */
  number?: string | null
  heading: string
  /** Nesting depth, 0 for top level. */
  level: number
  section_type?: SectionType | null
  page_range?: PageRange | null
  char_start?: number | null
  char_end?: number | null
  provision_ids?: AlephId[]
  children?: Section[]
  /** True when inferred from typography rather than an explicit heading. */
  is_heuristic?: boolean
}

export interface DocumentStructure {
  sections: Section[]
  numbering_scheme?: string | null
  max_depth?: number | null
  has_table_of_contents?: boolean
}

export type ProvisionType =
  | 'obligation'
  | 'prohibition'
  | 'permission'
  | 'entitlement'
  | 'benefit'
  | 'tax'
  | 'fee'
  | 'subsidy'
  | 'sanction'
  | 'funding_allocation'
  | 'institutional_mandate'
  | 'procedure'
  | 'eligibility_criterion'
  | 'definition'
  | 'transitional'
  | 'repeal'
  | 'amendment'
  | 'delegation'
  | 'reporting_requirement'
  | 'sunset'
  | 'other'

export type MechanismType =
  | 'transfer'
  | 'tax_change'
  | 'price_regulation'
  | 'quantity_regulation'
  | 'eligibility_change'
  | 'procedural_requirement'
  | 'institutional_creation'
  | 'information_requirement'
  | 'enforcement'
  | 'funding'
  | 'market_entry'
  | 'other'

/**
 * A provision as held inside the DocumentModel. The bundle also carries a
 * flattened projection of the same thing — see `Provision` below.
 */
export interface DocumentProvision {
  id: AlephId
  title?: string | null
  /** The provision's operative text, as extracted. Not paraphrased. */
  text: string
  provision_type: ProvisionType
  section_id?: string | null
  span: Span
  effective_date?: DateString | null
  effective_condition?: string | null
  sunset_date?: DateString | null
  amends?: string[]
  depends_on?: string[]
  implementing_body?: string | null
  /** HOW the provision produces its effect, drawn from the text. */
  mechanism?: string | null
  mechanism_type?: MechanismType | null
  conditions?: string[]
  exceptions?: string[]
  monetary_value_ids?: string[]
  quantity_ids?: string[]
  deadline_ids?: string[]
  affected_institutions?: string[]
  affected_populations?: string[]
  affected_industries?: string[]
  affected_regions?: string[]
  confidence?: Confidence | null
}

export interface Definition {
  id: string
  term: string
  definition_text: string
  scope?: string | null
  span: Span
  provision_id?: string | null
}

export type MonetaryRole =
  | 'cost'
  | 'revenue'
  | 'allocation'
  | 'transfer'
  | 'threshold'
  | 'cap'
  | 'floor'
  | 'penalty'
  | 'benefit_amount'
  | 'rate_base'
  | 'baseline'
  | 'projection'
  | 'other'

export type MonetaryRecurrence =
  | 'one_off'
  | 'annual'
  | 'monthly'
  | 'per_case'
  | 'cumulative'
  | 'unspecified'

export interface MonetaryValue {
  id: string
  label: string
  money: Money
  role: MonetaryRole
  recurrence?: MonetaryRecurrence | null
  fiscal_years?: number[]
  /** True when the document presents the figure as a projection. */
  is_estimate?: boolean
  provision_id?: string | null
  span: Span
}

export type QuantityRole =
  | 'threshold'
  | 'rate'
  | 'target'
  | 'baseline'
  | 'projection'
  | 'count_affected'
  | 'duration'
  | 'share'
  | 'other'

export interface QuantityMention {
  id: string
  label: string
  quantity: Quantity
  role?: QuantityRole
  provision_id?: string | null
  span: Span
}

export interface Deadline {
  id: string
  label: string
  date?: DateString | null
  relative_period?: string | null
  trigger?: string | null
  obligated_party?: string | null
  consequence_of_missing?: string | null
  provision_id?: string | null
  span: Span
}

export type AssumptionType =
  | 'macroeconomic'
  | 'behavioural'
  | 'demographic'
  | 'take_up'
  | 'compliance'
  | 'price'
  | 'implementation'
  | 'baseline'
  | 'administrative_capacity'
  | 'external_condition'
  | 'other'

/** A forecast is only evaluable against the assumptions the document states. */
export interface Assumption {
  id: string
  statement: string
  assumption_type: AssumptionType
  /** False means Aleph inferred it — the UI must label it as inferred. */
  is_explicit: boolean
  stated_by?: string | null
  quantified_money?: Money | null
  quantified_value?: Quantity | null
  sensitivity_note?: string | null
  applies_to_provision_ids?: string[]
  span: Span
}

export type CitationTargetKind =
  | 'statute'
  | 'regulation'
  | 'case'
  | 'dataset'
  | 'report'
  | 'article'
  | 'treaty'
  | 'standard'
  | 'internal'
  | 'other'

export interface Citation {
  id: string
  cited_text: string
  target_kind: CitationTargetKind
  target_identifier?: string | null
  target_title?: string | null
  url?: string | null
  provision_id?: string | null
  span: Span
}

export type AmendmentOperation =
  | 'insert'
  | 'replace'
  | 'delete'
  | 'renumber'
  | 'repeal'
  | 'extend'
  | 'suspend'
  | 'substitute'
  | 'other'

export interface Amendment {
  id: string
  operation: AmendmentOperation
  target_identifier?: string | null
  target_title?: string | null
  target_locator?: string | null
  before_text?: string | null
  after_text?: string | null
  provision_id?: string | null
  span: Span
}

export type DependencyKind =
  | 'requires_enactment'
  | 'requires_regulation'
  | 'requires_appropriation'
  | 'requires_ratification'
  | 'conditioned_on_event'
  | 'conflicts_with'
  | 'supersedes'
  | 'references'

export type DependencyStatus = 'met' | 'unmet' | 'partially_met' | 'unknown'

export interface LegalDependency {
  id: string
  dependency_kind: DependencyKind
  identifier?: string | null
  title?: string | null
  status?: DependencyStatus | null
  note?: string | null
  provision_ids?: string[]
  span?: Span | null
}

export type InstitutionRole =
  | 'implementing'
  | 'funding'
  | 'supervising'
  | 'reporting'
  | 'consulted'
  | 'beneficiary'
  | 'regulated'
  | 'created'
  | 'abolished'
  | 'other'

export interface AffectedInstitution {
  id: string
  name: string
  role_in_document: InstitutionRole
  provision_ids?: string[]
  span?: Span | null
}

export interface AffectedPopulation {
  id: string
  label: string
  /** The eligibility test the document states, verbatim where possible. */
  definition_criteria?: string | null
  /** Size only when the DOCUMENT states it. */
  estimated_size?: Quantity | null
  provision_ids?: string[]
  span?: Span | null
}

export interface AffectedIndustry {
  id: string
  label: string
  classification_code?: string | null
  classification_system?: string | null
  provision_ids?: string[]
  span?: Span | null
}

export type ExtractionWarningCode =
  | 'low_text_quality'
  | 'ocr_used'
  | 'missing_pages'
  | 'table_extraction_failed'
  | 'encrypted_file'
  | 'truncated_text'
  | 'ambiguous_numbering'
  | 'unresolved_reference'
  | 'mixed_languages'
  | 'scanned_images_only'
  | 'currency_ambiguous'
  | 'date_ambiguous'
  | 'number_format_ambiguous'
  | 'section_heuristic_fallback'
  | 'provision_boundary_uncertain'
  | 'other'

export type WarningSeverity = 'info' | 'warning' | 'error'

export interface ExtractionWarning {
  code: ExtractionWarningCode
  severity: WarningSeverity
  message: string
  page?: number | null
  /** Dotted path of the field whose reliability is reduced. */
  affected_field?: string | null
  span?: Span | null
}

/** Warm phase 1: the source document as parsed. Everything traces back here. */
export interface DocumentModel {
  schema_version?: SchemaVersion
  data_status?: DataStatus
  id: AlephId
  identity: DocumentIdentity
  source: DocumentSource
  structure: DocumentStructure
  provisions: DocumentProvision[]
  definitions?: Definition[]
  monetary_values?: MonetaryValue[]
  quantities?: QuantityMention[]
  deadlines?: Deadline[]
  assumptions?: Assumption[]
  citations?: Citation[]
  amendments?: Amendment[]
  legal_dependencies?: LegalDependency[]
  affected_institutions?: AffectedInstitution[]
  affected_populations?: AffectedPopulation[]
  affected_industries?: AffectedIndustry[]
  extraction_warnings?: ExtractionWarning[]
  notes?: string | null
}

/* ================================================================== *
 * proposition.json — atomic propositions (warm phase 2)
 * ================================================================== */

/** Provenance that MUST carry a span: an unquotable proposition is invalid. */
export interface GroundedProvenance extends Provenance {
  span: Span
}

/** Negation is structured because a dropped "not" inverts a verdict. */
export interface Negation {
  is_negated: boolean
  negated_element?: string | null
  cue_text?: string | null
}

/** Empty fields mean the document stated no limit, NOT that the claim is universal. */
export interface PropositionScope {
  temporal?: string | null
  geographic?: string | null
  population?: string | null
  conditions?: string[]
  exceptions?: string[]
}

export type PropositionType =
  | 'assertion_of_content'
  | 'quantitative'
  | 'temporal'
  | 'procedural'
  | 'conditional'
  | 'definitional'
  | 'assumption'

export type Modality =
  | 'asserted'
  | 'obligatory'
  | 'permissive'
  | 'prohibitive'
  | 'conditional'
  | 'hypothetical'
  | 'reported'
  | 'proposed'

/** One atomic, self-contained statement made by the document. */
export interface Proposition {
  id: AlephId
  text: string
  proposition_type: PropositionType
  statement_type?: StatementType | null
  subject?: string | null
  predicate_summary?: string | null
  object?: string | null
  quantities?: Quantity[]
  money?: Money[]
  provenance: GroundedProvenance
  derived_from_provision_id?: AlephId | null
  derived_from_section_id?: string | null
  /** Confidence in the extraction, not in the proposition being true of the world. */
  confidence?: Confidence | null
  negation?: Negation
  scope?: PropositionScope
  modality?: Modality | null
  hedges?: string[]
  is_atomic?: boolean
  is_self_contained?: boolean
  related_proposition_ids?: AlephId[]
  tags?: string[]
}

export interface PropositionCoverage {
  provisions_total?: number | null
  provisions_with_propositions?: number | null
  sections_not_processed?: string[]
  note?: string | null
}

/** Root object of proposition.json — this is what the bundle carries. */
export interface PropositionSet {
  schema_version?: SchemaVersion
  data_status?: DataStatus
  document_id: AlephId
  generated_at?: Timestamp | null
  extractor?: string | null
  propositions: Proposition[]
  coverage?: PropositionCoverage
  notes?: string | null
}

/* ================================================================== *
 * topic_graph.json — nodes + edges (warm phase 3)
 * ================================================================== */

export interface NodeAttribute {
  key: string
  value: string
  source_ref?: string | null
}

export type GraphNodeKind =
  | 'policy'
  | 'person_role'
  | 'institution'
  | 'company'
  | 'sector'
  | 'social_group'
  | 'tax'
  | 'right'
  | 'benefit'
  | 'obligation'
  | 'fiscal_effect'
  | 'region'
  | 'date'
  | 'provision'

export interface ExternalId {
  scheme: string
  value: string
}

/** `person_role` holds a ROLE, never a named individual. */
export interface GraphNode {
  id: AlephId
  kind: GraphNodeKind
  label: string
  aliases?: string[]
  description?: string | null
  /** Centrality within the document. A ranking aid, not a judgement of importance. */
  salience?: UnitInterval | null
  provision_ids?: AlephId[]
  proposition_ids?: AlephId[]
  evidence_refs?: AlephId[]
  mentions?: Span[]
  attributes?: NodeAttribute[]
  external_ids?: ExternalId[]
  confidence?: Confidence | null
}

export type GraphEdgeKind =
  | 'benefits'
  | 'costs'
  | 'regulates'
  | 'funds'
  | 'taxes'
  | 'replaces'
  | 'modifies'
  | 'restricts'
  | 'expands'
  | 'assumes'
  | 'affects'
  | 'depends_on'

/**
 * `document_explicit` — the text states it. `document_implicit` — it follows
 * from the text's own terms. `inferred` / `external_evidence` — Aleph derived
 * it. The UI MUST distinguish these.
 */
export type EdgeBasis = 'document_explicit' | 'document_implicit' | 'inferred' | 'external_evidence'

export interface GraphEdge {
  id: AlephId
  kind: GraphEdgeKind
  /** Edges are directed: "A taxes B" and "B taxes A" are different claims. */
  source: AlephId
  target: AlephId
  label?: string | null
  basis?: EdgeBasis
  direction?: Direction | null
  magnitude?: Magnitude | null
  time_horizon?: TimeHorizon | null
  causality?: Causality | null
  /** Without a mechanism an effect edge is unfalsifiable. */
  mechanism?: string | null
  quantity?: Quantity | null
  money?: Money | null
  conditions?: string[]
  evidence_refs: AlephId[]
  provenance?: Provenance | null
  confidence?: Confidence | null
  note?: string | null
}

export interface TopicGraphStats {
  node_count?: number | null
  edge_count?: number | null
  /** A graph that is mostly inferred is a hypothesis and should be labelled as one. */
  inferred_edge_count?: number | null
  unsupported_edge_count?: number | null
  isolated_node_count?: number | null
}

export interface TopicGraph {
  schema_version?: SchemaVersion
  data_status?: DataStatus
  document_id: AlephId
  generated_at?: Timestamp | null
  nodes: GraphNode[]
  edges: GraphEdge[]
  stats?: TopicGraphStats
  notes?: string | null
}

/* ================================================================== *
 * search_vocabulary.json — generated query terms (warm phase 4)
 * ================================================================== */

export type TargetSourceType =
  | 'news_outlet'
  | 'government_body'
  | 'statistics_agency'
  | 'legislature'
  | 'academic'
  | 'ngo'
  | 'aggregator'
  | 'search_engine'
  | 'social_media'
  | 'any'

export type QuerySyntax = 'plain' | 'phrase' | 'boolean' | 'site_scoped' | 'api_params'

export interface GeneratedQuery {
  id?: string | null
  query_text: string
  target_source_type: TargetSourceType
  target_source_ids?: AlephId[]
  expected_evidence_tier?: EvidenceTier | null
  language: string
  syntax?: QuerySyntax
  date_from?: DateString | null
  date_to?: DateString | null
  additional_terms?: string[]
  /** Execution order hint, 1 highest. Expected retrieval value only. */
  priority?: number
  rationale?: string | null
}

export type TermSource =
  | 'title'
  | 'heading'
  | 'entity'
  | 'identifier'
  | 'provision_heading'
  | 'definition'
  | 'abbreviation_expansion'
  | 'synonym_expansion'
  | 'translation'
  | 'model_expansion'
  | 'registry'
  | 'manual'

export interface VocabularyTerm {
  id?: string | null
  text: string
  language: string
  /** Expected retrieval value. A search-utility weight, with no evaluative meaning. */
  weight: UnitInterval
  source: TermSource
  normalized_form?: string | null
  must_quote?: boolean
  ambiguity_note?: string | null
  derived_from?: string | null
  span?: Span | null
  generated_queries?: GeneratedQuery[]
}

/** All ten keys required. An empty set is a reportable retrieval gap. */
export interface TermSets {
  official_names: VocabularyTerm[]
  common_names: VocabularyTerm[]
  identifiers: VocabularyTerm[]
  abbreviations: VocabularyTerm[]
  political_terminology: VocabularyTerm[]
  technical_terminology: VocabularyTerm[]
  sector_terminology: VocabularyTerm[]
  synonyms: VocabularyTerm[]
  provision_names: VocabularyTerm[]
  actor_terms: VocabularyTerm[]
}

export interface SearchVocabulary {
  schema_version?: SchemaVersion
  data_status?: DataStatus
  document_id: AlephId
  generated_at?: Timestamp | null
  primary_language: string
  target_languages?: string[]
  term_sets: TermSets
  expansion_notes?: string | null
  known_gaps?: string[]
}

/* ================================================================== *
 * evidence.json — the evidence pool (warm phase 5)
 * ================================================================== */

/**
 * Relevance is a property of the (item, question) pair, never of the
 * publisher's standing. `cannot_establish` is required for a reason.
 */
export interface EvidentialRelevance {
  question: string
  relevance: UnitInterval
  can_establish: string[]
  cannot_establish: string[]
  why?: string | null
}

export interface EvidenceItem {
  id: AlephId
  source_ref: SourceRef
  tier: EvidenceTier
  /** What this item actually establishes, scoped as narrowly as the source permits. */
  statement: string
  spans: Span[]
  retrieved_at: Timestamp
  supports: AlephId[]
  contradicts: AlephId[]
  evidential_relevance: EvidentialRelevance
  strength?: EvidenceStrength
  independence?: Independence
  derived_from_evidence_id?: AlephId | null
  quantities?: Quantity[]
  money?: Money[]
  confidence?: Confidence
  uncertainties?: Uncertainty[]
  extraction_method?: string | null
  notes?: string | null
}

export interface EvidenceSet {
  id: AlephId
  question: string
  evidence_ids: AlephId[]
  strength: EvidenceStrength
  /** Distinct originals after collapsing syndication. This is what corroboration means. */
  independent_source_count: number
  gaps?: string[]
  summary: string
  confidence?: Confidence
}

export interface RetrievalGap {
  question: string
  queries_tried?: string[]
  expected_source_kind?: EvidenceTier | null
  note: string
}

/** Root object of evidence.json (`public/data/evidence/<slug>.json`). */
export interface EvidencePool {
  schema_version: SchemaVersion
  data_status: DataStatus
  generated_at: Timestamp
  document_id?: AlephId | null
  evidence: EvidenceItem[]
  evidence_sets?: EvidenceSet[]
  retrieval_gaps?: RetrievalGap[]
}

/* ================================================================== *
 * claim.json — claims, blind evaluation, attributed analysis
 * ================================================================== */

/** The ten fixed epistemic checks applied to every factual claim. */
export type CheckName =
  | 'direct_textual_evidence'
  | 'data_consistency'
  | 'quantitative_correctness'
  | 'logical_validity'
  | 'causal_support'
  | 'uncertainty_handling'
  | 'context_completeness'
  | 'temporal_correctness'
  | 'independent_corroboration'
  | 'contradiction_with_stronger_evidence'

export type CheckOutcome = 'pass' | 'fail' | 'na'

export interface CheckResult {
  check: CheckName
  result: CheckOutcome
  /** Required key: a result without a reason is not inspectable. */
  note: string | null
  evidence_refs?: AlephId[]
}

export type WithheldAttribute =
  | 'speaker_name'
  | 'speaker_role'
  | 'party'
  | 'coalition'
  | 'government_or_opposition_status'
  | 'outlet'
  | 'outlet_prestige'
  | 'author'
  | 'publication_venue'
  | 'institutional_affiliation'

/** Exactly what the blind evaluator was shown, so blindness is auditable. */
export interface RedactedContext {
  claim_text: string
  context_excerpts?: string[]
  evidence_ids: AlephId[]
  /** Non-empty: an evaluation that withheld nothing is not blind. */
  withheld: WithheldAttribute[]
  redaction_version: string
}

/**
 * STAGE ONE. The only place a verdict may be written. Speaker, party,
 * coalition, government-or-opposition status and outlet were withheld — this
 * type has no property in which any of them could be recorded.
 */
export interface BlindEvaluation {
  evaluator_version: string
  redacted_context: RedactedContext
  verdict: Verdict
  /** The chain from evidence to verdict. Never refers to who made the claim. */
  reasoning: string
  evidence_refs: AlephId[]
  assumptions_required?: string[]
  confidence: Confidence
  uncertainties?: Uncertainty[]
}

export type HistoricalConsistencyAssessment =
  | 'consistent'
  | 'shifted'
  | 'contradicts_prior'
  | 'insufficient_history'
  | 'not_assessed'

/** Descriptive context, not a truth test. Inconsistency never alters a verdict. */
export interface HistoricalConsistency {
  assessment: HistoricalConsistencyAssessment
  prior_claim_refs?: AlephId[]
  note?: string | null
}

export type RhetoricalPattern =
  | 'appeal_to_authority'
  | 'false_dilemma'
  | 'cherry_picked_statistic'
  | 'anecdote_as_evidence'
  | 'unfalsifiable_prediction'
  | 'straw_man'
  | 'loaded_comparison'
  | 'urgency_framing'
  | 'moral_framing'
  | 'technical_obfuscation'
  | 'none_detected'

/** Naming a rhetorical pattern is not a refutation. */
export interface RhetoricalObservation {
  pattern: RhetoricalPattern
  span?: Span | null
  note?: string | null
}

/**
 * STAGE TWO. Applied only after the blind verdict exists. There is no verdict,
 * confidence, override or adjustment field here, by design.
 */
export interface AttributedAnalysis {
  /** Pinned true: attribution never precedes evaluation. */
  applied_after_verdict: true
  /** A generic functional role, never a person. */
  speaker_role?: string | null
  speaker_id?: AlephId | null
  outlet_id?: AlephId | null
  framing_notes?: string[]
  historical_consistency?: HistoricalConsistency | null
  rhetorical_pattern?: RhetoricalObservation[]
}

/** Material context a reader would need that the claim or article left out. */
export interface OmittedContext {
  statement: string
  why_it_matters: string
  evidence_refs?: AlephId[]
  materiality?: Magnitude
}

/**
 * A single assertion plus everything Aleph did with it. Note what is NOT here:
 * no top-level verdict, no confidence, no score.
 */
export interface Claim {
  id: AlephId
  /** The claim exactly as asserted, verbatim. */
  text: string
  /** The same claim restated as one checkable proposition. */
  normalised_text: string
  statement_type: StatementType
  topic_refs?: AlephId[]
  made_at: Timestamp | DateString | null
  provenance: Provenance
  quantities?: Quantity[]
  money?: Money[]
  blind_evaluation: BlindEvaluation
  attributed_analysis: AttributedAnalysis | null
  checks_applied: CheckResult[]
  contradicts?: AlephId[]
  cluster_id?: AlephId | null
  omitted_context?: OmittedContext[]
  article_id?: AlephId | null
  proposition_refs?: AlephId[]
}

/** Root object of claim.json (`public/data/claims/<slug>.json`). */
export interface ClaimSet {
  schema_version: SchemaVersion
  data_status: DataStatus
  generated_at: Timestamp
  document_id?: AlephId | null
  claims: Claim[]
}

/* ================================================================== *
 * news_article.json — coverage
 * ================================================================== */

export type ArticleType =
  | 'news_report'
  | 'analysis'
  | 'opinion_column'
  | 'editorial'
  | 'interview'
  | 'fact_check'
  | 'press_release'
  | 'wire'

/** Carries no prestige, tier or credibility rating, by design. */
export interface Publisher {
  id: AlephId
  name: string
}

export interface Quotation {
  text: string
  /** Generic functional role. Never a private individual's name in synthetic data. */
  speaker_role: string | null
  span: Span
  claim_id?: AlephId | null
}

/** Predictions cannot be true or false yet — only conditional and checkable later. */
export interface Prediction {
  text: string
  speaker_role?: string | null
  horizon: TimeHorizon
  conditions?: string[]
  /** If false, the prediction is rhetoric and must not be shown as a checkable forecast. */
  falsifiable: boolean
  evaluable_after?: DateString | null
  claim_id?: AlephId | null
}

export interface ImpactEmphasisEntry {
  axis: ImpactAxisKey
  emphasis: UnitInterval
  direction_emphasised?: Direction
  note?: string | null
}

export type PrimarySourceGroundingKind =
  | 'quoted_directly'
  | 'linked'
  | 'paraphrased'
  | 'named_without_link'
  | 'none'

export interface PrimarySourceGroundingEntry {
  ref: AlephId
  kind: PrimarySourceGroundingKind
  note?: string | null
}

export interface NewsArticle {
  id: AlephId
  /** Null for synthetic items, which point at nothing because they describe nothing real. */
  url: string | null
  headline: string
  dek?: string | null
  publisher: Publisher
  /** A generic role string in synthetic data; null when unbylined. */
  author: string | null
  published_at: Timestamp | DateString | null
  retrieved_at: Timestamp
  language?: string | null
  article_type: ArticleType
  word_count?: number | null
  neutral_summary: string
  /** False means extraction saw only headline and dek. */
  body_available: boolean
  paywalled: boolean
  claim_ids: AlephId[]
  quotations?: Quotation[]
  predictions?: Prediction[]
  /** Never collapse the referenced profile into a single bias number. */
  framing_profile_id?: string | null
  impact_emphasis?: ImpactEmphasisEntry[]
  omitted_context?: OmittedContext[]
  primary_source_grounding?: PrimarySourceGroundingEntry[]
  independence: Independence
  derived_from_article_id?: AlephId | null
  cluster_ids?: AlephId[]
  confidence?: Confidence
}

/** Root object of news_article.json. */
export interface NewsArticleSet {
  schema_version: SchemaVersion
  data_status: DataStatus
  generated_at: Timestamp
  document_id?: AlephId | null
  articles: NewsArticle[]
}

/* ================================================================== *
 * news_cluster.json — clusters + independence (warm phase 6)
 * ================================================================== */

export type ClusterKind = 'story_cluster' | 'claim_cluster' | 'reform_component' | 'event'

export interface DateRange {
  start: DateString
  end: DateString
}

export type SyndicationChainKind =
  | 'wire_redistribution'
  | 'press_release_pickup'
  | 'verbatim_reuse'
  | 'translation'
  | 'aggregation'
  | 'unknown'

export interface SyndicationChain {
  origin_article_id: AlephId
  /** Items that reproduce the origin. They contribute nothing to corroboration. */
  downstream_article_ids: AlephId[]
  chain_kind: SyndicationChainKind
  evidence: string
  confidence?: Confidence
}

export type SharedOriginSignalKind =
  | 'identical_phrasing'
  | 'identical_quote_set'
  | 'same_wire_slug'
  | 'same_press_release'
  | 'same_dataset_release'
  | 'same_publication_minute'
  | 'shared_error'

export interface SharedOriginSignal {
  kind: SharedOriginSignalKind
  article_ids: AlephId[]
  similarity?: UnitInterval
  detail: string
}

/**
 * The count that matters. `total_articles` measures how loud coverage was;
 * `distinct_original_sources` measures how much was actually observed.
 */
export interface IndependenceAnalysis {
  distinct_original_sources: number
  /** A volume measure, never an evidence measure. */
  total_articles: number
  syndication_chains: SyndicationChain[]
  shared_origin_evidence: SharedOriginSignal[]
  /** The only number here that may move confidence. */
  independent_corroboration_count: number
  note?: string | null
}

export interface NewsCluster {
  id: AlephId
  kind: ClusterKind
  label: string
  summary?: string | null
  article_ids: AlephId[]
  claim_ids: AlephId[]
  date_range: DateRange
  independence_analysis: IndependenceAnalysis
  topic_refs?: AlephId[]
  confidence?: Confidence
  uncertainties?: Uncertainty[]
}

/** Root object of news_cluster.json. */
export interface NewsClusterSet {
  schema_version: SchemaVersion
  data_status: DataStatus
  generated_at: Timestamp
  document_id?: AlephId | null
  clusters: NewsCluster[]
}

/* ================================================================== *
 * framing_profile.json — eight dimensions, never one number
 * ================================================================== */

export type FramingDimensionKey =
  | 'selection_asymmetry'
  | 'loaded_language'
  | 'context_omission'
  | 'certainty_inflation'
  | 'unsupported_causal_language'
  | 'opinion_as_fact'
  | 'source_diversity'
  | 'primary_source_grounding'

/** A 0–100 framing measurement. The score exists only alongside its components. */
export interface FramingDimension {
  score: Score100
  polarity: Polarity
  components: Component[]
  evidence_refs?: AlephId[]
  confidence: Confidence
  /** Plain-language justification a reader can argue with. */
  rationale: string
}

export interface FramingDimensionLowerIsBetter extends FramingDimension {
  polarity: 'lower_is_better'
}

export interface FramingDimensionHigherIsBetter extends FramingDimension {
  polarity: 'higher_is_better'
}

/** Exactly these eight keys. No ninth dimension, least of all a summary figure. */
export interface FramingDimensions {
  selection_asymmetry: FramingDimensionLowerIsBetter
  loaded_language: FramingDimensionLowerIsBetter
  context_omission: FramingDimensionLowerIsBetter
  certainty_inflation: FramingDimensionLowerIsBetter
  unsupported_causal_language: FramingDimensionLowerIsBetter
  opinion_as_fact: FramingDimensionLowerIsBetter
  source_diversity: FramingDimensionHigherIsBetter
  primary_source_grounding: FramingDimensionHigherIsBetter
}

export interface FramingProfile {
  id: string
  article_id: AlephId
  profile_version: string
  generated_at?: Timestamp
  dimensions: FramingDimensions
  /** Must describe the pattern across dimensions rather than average them. */
  overall_note?: string | null
  confidence?: Confidence
  limitations?: string[]
}

/* ================================================================== *
 * impact_map.json — seven policy-effect axes. NOT party labels.
 * ================================================================== */

export type ImpactAxisKey =
  | 'households_vs_firms'
  | 'redistribution_vs_growth'
  | 'public_vs_private_provision'
  | 'worker_protection_vs_flexibility'
  | 'environment_vs_project_acceleration'
  | 'central_vs_local'
  | 'current_relief_vs_long_term_investment'

/**
 * A bipolar placement with everything needed to audit it. A score near zero may
 * mean balanced effects OR offsetting effects OR no relevant provisions — which
 * is why `components` and `rationale` are required and the number alone never is.
 */
export interface ImpactAxis {
  score: BipolarScore
  /** Plain-language name of the negative pole (the first-named half of the key). */
  negative_label: string
  positive_label: string
  /** This array IS the finding; the score is only its summary. */
  components: Component[]
  evidence_refs: AlephId[]
  confidence: Confidence
  rationale: string
}

export type ImpactAxes = Record<ImpactAxisKey, ImpactAxis>

/** One group and how a document's provisions are estimated to reach it. */
export interface GroupImpact {
  group: string
  group_detail?: string | null
  /** `mixed` and `uncertain` are first-class answers; never round them. */
  estimated_direction: Direction
  magnitude: Magnitude
  evidence_quality: EvidenceStrength
  time_horizon: TimeHorizon
  direct_or_indirect: Causality
  supporting_evidence: AlephId[]
  rationale: string
  uncertainties?: Uncertainty[]
  money?: Money[] | null
  confidence?: Confidence
}

export interface ImpactMap {
  schema_version: SchemaVersion
  data_status: DataStatus
  generated_at: Timestamp
  document_id: AlephId
  map_version?: string
  axes: ImpactAxes
  beneficiaries: GroupImpact[]
  cost_bearers: GroupImpact[]
  method_note?: string | null
  uncertainties?: Uncertainty[]
}

/* ================================================================== *
 * contradiction.json — disputes adjudicated on shared evidence
 * ================================================================== */

export type Stance =
  | 'affirms'
  | 'denies'
  | 'qualified_affirm'
  | 'qualified_deny'
  | 'reframes'
  | 'not_responsive'

export interface Position {
  claim_id: AlephId
  /** Reader orientation only. Carries no evidential weight. */
  speaker_role?: string | null
  stance: Stance
  summary: string
  evidence_cited_by_actor?: AlephId[]
}

export interface SharedEvidenceItem {
  evidence_id: AlephId
  what_it_establishes: string
  /** Required: the asymmetry between these two fields is where a dispute lives. */
  what_it_cannot_establish: string
  bears_on_positions?: AlephId[]
}

export interface SourceStatement {
  statement: string
  evidence_refs?: AlephId[]
  assumptions?: string[]
}

/** Derived only from shared evidence. Speaker identity is not an input. */
export interface AlephConclusion {
  statement: string
  verdict: Verdict
  confidence: Confidence
  reasoning: string
  evidence_refs?: AlephId[]
}

export interface ContradictionCluster {
  id: AlephId
  /** The single proposition the actors are actually disputing. */
  question_at_issue: string
  positions: Position[]
  shared_evidence: SharedEvidenceItem[]
  what_the_primary_source_says: SourceStatement | null
  what_projections_say: SourceStatement | null
  what_is_uncertain: Uncertainty[]
  aleph_conclusion: AlephConclusion
  /** False means no amount of analysis of current sources will decide it. */
  resolvable: boolean
  resolvable_by?: string | null
  topic_refs?: AlephId[]
  cluster_id?: AlephId | null
}

/** Root object of contradiction.json. */
export interface ContradictionSet {
  schema_version: SchemaVersion
  data_status: DataStatus
  generated_at: Timestamp
  document_id?: AlephId | null
  clusters: ContradictionCluster[]
}

/* ================================================================== *
 * neutrality_report.json — Aleph measuring its own behaviour
 * ================================================================== */

export interface NeutralitySample {
  claims_tested: number
  runs_total: number
  claim_ids?: AlephId[]
  selection_method?: string | null
}

export interface ExampleDelta {
  /** Perturbed evidence_confidence minus original. Should be near zero. */
  confidence_delta: number
  framing_delta?: number
  explanation_semantic_delta: UnitInterval
  verdict_changed: boolean
}

export type PerturbationName =
  | 'speaker_swap'
  | 'source_swap'
  | 'party_swap'
  | 'authority_removal'
  | 'claim_paraphrase'
  | 'evidence_order_shuffle'

export interface PerturbationExample {
  claim_id: AlephId
  perturbation?: PerturbationName | null
  /** Described without naming any real person or organisation. */
  substitution?: string | null
  original_verdict: Verdict
  perturbed_verdict: Verdict
  delta: ExampleDelta
  note?: string | null
}

export interface PerturbationResult {
  runs: number
  /** Every flip here is by construction unwarranted. */
  flips: number
  flip_rate?: UnitInterval
  examples: PerturbationExample[]
  note?: string | null
}

export type Perturbations = Record<PerturbationName, PerturbationResult>

export interface NeutralityMetrics {
  /** The headline defect measure; the target is zero. */
  verdict_flip_rate: UnitInterval
  confidence_delta: number
  framing_delta: number
  explanation_semantic_delta: UnitInterval
}

export interface NeutralityReport {
  schema_version: SchemaVersion
  data_status: DataStatus
  generated_at: Timestamp
  report_version: string
  evaluator_version: string
  sample: NeutralitySample
  perturbations: Perturbations
  metrics: NeutralityMetrics
  /** A measure of Aleph's own behaviour, not of any document, outlet or actor. */
  neutrality_health: Score100
  neutrality_health_polarity?: 'higher_is_better'
  neutrality_health_components: Component[]
  confidence: Confidence
  /** REQUIRED wherever neutrality_health is displayed. */
  interpretation_caveat: string
  limitations?: string[]
  failures_to_investigate?: PerturbationExample[]
}

/* ================================================================== *
 * readiness.json — the publication gate (warm phase 7)
 * ================================================================== */

export type ReadinessDimensionKey =
  | 'document_understanding'
  | 'primary_source_coverage'
  | 'news_coverage'
  | 'temporal_coverage'
  | 'evidence_diversity'
  | 'claim_coverage'
  | 'source_independence'

export type GapSeverity = 'blocking' | 'major' | 'minor'

export type MissingKind =
  | 'primary_document'
  | 'official_data'
  | 'independent_reporting'
  | 'expert_analysis'
  | 'counter_evidence'
  | 'time_period'
  | 'quantitative_check'
  | 'document_section'
  | 'assumption_statement'
  | 'translation'
  | 'other'

/** Gaps are written to be actionable: a low score should read as a task. */
export interface ReadinessGap {
  id?: string | null
  dimension?: ReadinessDimensionKey | null
  description: string
  severity: GapSeverity
  missing_kind: MissingKind
  what_would_resolve?: string | null
  affected_claim_ids?: AlephId[]
  blocking_since?: Timestamp | null
}

export interface ReadinessDimensionScore {
  /** 0–100, higher is better. Measures Aleph's coverage, not the document's merit. */
  score: Score100
  weight: number
  rationale: string
  components: Component[]
  gaps: ReadinessGap[]
  confidence?: Confidence | null
}

export type ReadinessDimensions = Record<ReadinessDimensionKey, ReadinessDimensionScore>

export interface EvidenceInventory {
  evidence_items?: number | null
  primary_documents?: number | null
  statistical_datasets?: number | null
  articles?: number | null
  clusters?: number | null
  independent_sources?: number | null
  distinct_tiers?: number | null
  claims_total?: number | null
  claims_with_evidence?: number | null
  propositions_total?: number | null
  earliest_evidence_date?: DateString | null
  latest_evidence_date?: DateString | null
}

export type PhaseState = 'not_started' | 'running' | 'complete' | 'failed' | 'skipped'

export interface PhaseStatusEntry {
  phase: WarmPhase
  state: PhaseState
  completed_at?: Timestamp | null
  item_count?: number | null
  note?: string | null
}

/**
 * The gate the rest of the bundle must be read through. Model confidence may
 * never be used to paper over an `insufficient` state.
 */
export interface Readiness {
  schema_version?: SchemaVersion
  data_status?: DataStatus
  document_id: AlephId
  generated_at?: Timestamp | null
  overall_state: ReadinessState
  overall_score: Score100
  polarity?: 'higher_is_better'
  dimensions: ReadinessDimensions
  blocking_gaps: ReadinessGap[]
  /** Decided by evidence coverage alone; no level of model confidence may flip it. */
  publishable: boolean
  /** Non-empty whenever `publishable` is false. */
  why_not_publishable: string | null
  confidence: Confidence
  evidence_inventory?: EvidenceInventory
  phase_status?: PhaseStatusEntry[]
  recommended_actions?: string[]
  notes?: string | null
}

/* ================================================================== *
 * source_registry.json
 * ================================================================== */

export type SourceEntryKind =
  | 'news_outlet'
  | 'government_body'
  | 'statistics_agency'
  | 'legislature'
  | 'academic'
  | 'ngo'
  | 'aggregator'

export type FeedFormat = 'rss' | 'atom' | 'sitemap' | 'api' | 'json' | 'html_index'

export interface Feed {
  url: string
  format: FeedFormat
  label?: string | null
  language?: string | null
  topic_hint?: string | null
  /** Credentials are never stored in this file or in any shipped artefact. */
  auth_required?: boolean
  enabled?: boolean
}

export interface RobotsPolicy {
  respect_robots: boolean
  robots_url?: string | null
  crawl_allowed?: boolean | null
  terms_url?: string | null
  user_agent?: string | null
  notes?: string | null
}

export interface RateLimit {
  requests_per_minute?: number | null
  min_interval_seconds?: number | null
  max_concurrent?: number | null
  backoff_seconds?: number | null
  daily_request_cap?: number | null
}

export type PaywallKind = 'none' | 'metered' | 'hard' | 'registration' | 'unknown'

/** Every field answers "what is this and how do we reach it", never "what is it worth". */
export interface SourceEntry {
  id: AlephId
  name: string
  kind: SourceEntryKind
  jurisdiction: Jurisdiction
  base_url: string
  feeds?: Feed[]
  language: string
  additional_languages?: string[]
  /** Constrains what the source can establish. NOT a ranking. */
  evidence_tier: EvidenceTier
  /** Factual, public-record disclosure. Aleph MUST NOT convert it into a score. */
  ownership_note?: string | null
  typical_independence: Independence
  robots_policy?: RobotsPolicy
  rate_limit?: RateLimit
  enabled: boolean
  topics?: string[]
  paywall?: PaywallKind | null
  added_at?: DateString | null
  last_verified_at?: Timestamp | null
  notes?: string | null
}

export interface SourceRegistry {
  schema_version?: SchemaVersion
  generated_at?: Timestamp | null
  registry_version?: string | null
  default_rate_limit?: RateLimit | null
  sources: SourceEntry[]
  notes?: string | null
}

/* ================================================================== *
 * analysis_bundle.json — THE frontend contract
 * ================================================================== */

/**
 * One operative provision in the shape the interface needs. Denormalised from
 * `document` for rendering; where the two disagree, `document` wins.
 */
export interface Provision {
  id: AlephId
  /** The document's own label, e.g. an article number, exactly as printed. */
  ref_label?: string | null
  title?: string | null
  summary: string
  /** The operative text, verbatim. Null weakens every downstream use of it. */
  text?: string | null
  spans?: Span[]
  quantities?: Quantity[]
  money?: Money[]
  topic_refs?: AlephId[]
  /** How a reader gets from a dial back to a clause. */
  impact_axis_refs?: ImpactAxisKey[]
  proposition_refs?: AlephId[]
  /** Copied from the source, never inferred. */
  status?: string | null
}

/** Alias for the schema's own name for the same object. */
export type ProvisionSummary = Provision

export type TimelineEventKind =
  | 'document_published'
  | 'document_revised'
  | 'committee_stage'
  | 'vote'
  | 'amendment'
  | 'official_report'
  | 'statement'
  | 'media_event'
  | 'implementation_milestone'
  | 'legal_challenge'
  | 'other'

/** A timeline is a set of factual assertions like any other. */
export interface TimelineEvent {
  date: DateString
  label: string
  description?: string | null
  kind: TimelineEventKind
  /** An entry with none must be treated as unverified. */
  evidence_refs: AlephId[]
}

/** Alias for the schema's own name for the same object. */
export type TimelineEntry = TimelineEvent

/** What produced this bundle and what it cannot do. `limitations` is non-empty. */
export interface Methodology {
  pipeline_version: string
  /** Which model judged these claims. A reader is entitled to know. */
  model_provider: string
  phases_completed: WarmPhase[]
  limitations: string[]
  generated_by: string
}

/**
 * One document's complete analysis. Read it as a chain of custody: the warm
 * phases first, then the evaluated material, then `readiness` — which may say
 * the evidence base was never thick enough to publish verdicts at all.
 *
 * `data_status` is required and must be shown to the reader. A bundle marked
 * `synthetic` describes no real statement by any real person or outlet.
 */
export interface AnalysisBundle {
  schema_version: SchemaVersion
  data_status: DataStatus
  generated_at: Timestamp
  document: DocumentModel
  /** The proposition.json ROOT object — the array lives at `.propositions`. */
  propositions: PropositionSet
  topic_graph: TopicGraph
  search_vocabulary: SearchVocabulary
  provisions: Provision[]
  impact_map: ImpactMap
  claims: Claim[]
  evidence: EvidenceItem[]
  articles: NewsArticle[]
  clusters: NewsCluster[]
  contradictions: ContradictionCluster[]
  neutrality_report: NeutralityReport
  readiness: Readiness
  timeline: TimelineEvent[]
  methodology: Methodology
  /** Optional. Never optional to display in full once present. */
  framing_profiles?: FramingProfile[]
  source_registry?: SourceRegistry
  /** Attributed-stage context, structurally separate from blind verdicts. */
  actor_profiles?: ActorProfileSet
}

/* ================================================================== *
 * actor_profile.json — attributed-stage context only
 * ================================================================== */

export interface ActorRole {
  title: string
  institution?: string
  level:
    | 'national_executive'
    | 'national_legislative'
    | 'regional'
    | 'municipal'
    | 'judicial'
    | 'central_bank'
    | 'agency'
    | 'civil_society'
    | 'private_sector'
    | 'other'
  from?: DateString | null
  to?: DateString | null
  source: SourceRef
}

export interface ActorAffiliation {
  organisation: string
  kind:
    | 'party'
    | 'coalition'
    | 'union'
    | 'business_association'
    | 'ngo'
    | 'professional_body'
    | 'other'
  from?: DateString | null
  to?: DateString | null
  source: SourceRef
}

export interface DeclaredInterest {
  kind:
    | 'asset'
    | 'shareholding'
    | 'directorship'
    | 'employment'
    | 'consultancy'
    | 'property'
    | 'debt'
    | 'family_interest'
    | 'other'
  description: string
  declared_on?: DateString | null
  relevance_to_document: string
  relevant_provision_ids?: AlephId[]
  source: SourceRef
}

export interface LegalRecordEntry {
  summary: string
  status:
    | 'investigation_reported'
    | 'formally_investigated'
    | 'charged'
    | 'trial_ongoing'
    | 'convicted'
    | 'acquitted'
    | 'dismissed'
    | 'case_closed'
    | 'administrative_sanction'
    | 'sanction_overturned'
    | 'unknown'
  resolved: boolean
  body: string
  date?: DateString | null
  presumption_note: string | null
  source: SourceRef
  additional_coverage?: SourceRef[]
}

export interface ClaimTrackRecord {
  sample_size: number
  by_verdict: Partial<Record<Verdict, number>>
  by_statement_type?: Partial<Record<StatementType, number>>
  evaluated_claim_ids: AlephId[]
  period?: { from: DateString; to: DateString }
  caveat: string
}

export interface ActorFramingPattern {
  recurring_emphases?: string[]
  recurring_omissions?: string[]
  certainty_tendency?: 'overstates' | 'calibrated' | 'understates' | 'insufficient_data'
  components: Component[]
  confidence: Confidence
}

export interface ActorProfile {
  id: AlephId
  display_name: string
  is_natural_person: boolean
  jurisdiction?: string
  roles: ActorRole[]
  affiliations?: ActorAffiliation[]
  declared_interests?: DeclaredInterest[]
  legal_record?: LegalRecordEntry[]
  claim_track_record?: ClaimTrackRecord
  framing_pattern?: ActorFramingPattern
  profile_uncertainties?: Uncertainty[]
  sources: SourceRef[]
}

export interface ActorProfileSet {
  schema_version: SchemaVersion
  data_status: DataStatus
  generated_at: Timestamp
  /** Pinned false: profiles can only enter the attributed presentation stage. */
  usable_in_blind_evaluation: false
  actors: ActorProfile[]
}

/* ================================================================== *
 * Site-level static data (frontend-owned shapes)
 * ================================================================== */

export interface SiteIndexCounts {
  provisions?: number
  propositions?: number
  claims?: number
  evidence?: number
  articles?: number
  clusters?: number
  contradictions?: number
}

/** One analysis listed on the home page. */
export interface SiteIndexEntry {
  /** URL key; the bundle lives at `data/reforms/<slug>.json`. */
  slug: string
  title: string
  short_title?: string | null
  subtitle?: string | null
  summary?: string | null
  document_type?: DocumentType | null
  /** Human-readable jurisdiction name, for display only. */
  jurisdiction?: string | null
  institution?: string | null
  language?: string | null
  status?: DocumentStatus | null
  data_status: DataStatus
  generated_at: Timestamp
  published_at?: DateString | null
  readiness_state?: ReadinessState | null
  readiness_score?: Score100 | null
  publishable?: boolean | null
  counts?: SiteIndexCounts
  /** Path relative to `data/`, e.g. `reforms/18216-05.json`. */
  path?: string
}

export interface SiteNewsPointer {
  /** Path relative to `data/`, e.g. `news/latest.json`. */
  path?: string
  article_count?: number
  latest_published_at?: Timestamp | DateString | null
}

/** `public/data/index.json` — the site manifest. */
export interface SiteIndex {
  schema_version: SchemaVersion
  data_status: DataStatus
  generated_at: Timestamp
  /** Slug of the analysis to feature on the home page. */
  featured?: string | null
  analyses: SiteIndexEntry[]
  news?: SiteNewsPointer | null
}

/** One entry of the cross-analysis news feed, with its summary metrics. */
export interface NewsFeedItem {
  article: NewsArticle
  /** Analysis this coverage belongs to, so the item can link back. */
  document_slug?: string | null
  document_title?: string | null
  framing_profile?: FramingProfile | null
  claim_count?: number
  /** How many of this article's claims landed on each verdict. */
  verdict_counts?: Partial<Record<Verdict, number>>
  cluster_id?: AlephId | null
  /** Independent originals in this article's cluster — not the article count. */
  independent_source_count?: number
}

/** Acquisition counts stay separate so repeated coverage is never presented as independent evidence. */
export interface NewsFeedCounts {
  articles: number
  distinct_outlets: number
  original_reporting: number
  clusters: number
}

/** `public/data/news/latest.json`. */
export interface NewsFeed {
  schema_version: SchemaVersion
  data_status: DataStatus
  generated_at: Timestamp
  notice?: string
  retrieval_mode?: 'manual' | 'on_demand' | 'scheduled' | 'disabled'
  retrieval_note?: string
  counts?: NewsFeedCounts
  items: NewsFeedItem[]
}

/* ================================================================== *
 * Display metadata — Spanish labels for the fixed vocabularies
 *
 * These live beside the types because the key sets are part of the data
 * contract: they are fixed so two documents are always described along the
 * same dimensions, and so no axis can be invented to flatter a conclusion.
 * ================================================================== */

export interface FramingDimensionMeta {
  key: FramingDimensionKey
  label: string
  polarity: 'lower_is_better' | 'higher_is_better'
  /** What a score near 0 means, in words. */
  low_label: string
  /** What a score near 100 means, in words. */
  high_label: string
  description: string
}

/**
 * The eight framing dimensions, in display order. Six are lower-is-better and
 * two are higher-is-better; the polarity is pinned so a value can never be
 * mis-coloured. These eight numbers must never be collapsed into one.
 */
export const FRAMING_DIMENSIONS: readonly FramingDimensionMeta[] = [
  {
    key: 'selection_asymmetry',
    label: 'Asimetría de selección',
    polarity: 'lower_is_better',
    low_label: 'Selección pareja',
    high_label: 'Selección muy asimétrica',
    description:
      'Qué tan desigualmente el artículo elige qué datos, cifras y voces incluir, medido contra lo que la fuente primaria y la evidencia disponible sí contenían.',
  },
  {
    key: 'loaded_language',
    label: 'Lenguaje cargado',
    polarity: 'lower_is_better',
    low_label: 'Lenguaje descriptivo',
    high_label: 'Lenguaje muy cargado',
    description:
      'Uso de términos evaluativos o emocionales donde existía una descripción neutra. Cada componente cita las palabras concretas.',
  },
  {
    key: 'context_omission',
    label: 'Omisión de contexto',
    polarity: 'lower_is_better',
    low_label: 'Contexto completo',
    high_label: 'Omisiones importantes',
    description:
      'Contexto material que el lector necesita y el artículo deja fuera: un año base, una clase de comparación, una disposición que compensa.',
  },
  {
    key: 'certainty_inflation',
    label: 'Inflación de certeza',
    polarity: 'lower_is_better',
    low_label: 'Certeza proporcionada',
    high_label: 'Certeza inflada',
    description:
      'Presentar proyecciones, estimaciones o cifras en disputa con más certeza de la que sus propias fuentes declaran.',
  },
  {
    key: 'unsupported_causal_language',
    label: 'Causalidad sin respaldo',
    polarity: 'lower_is_better',
    low_label: 'Causalidad respaldada',
    high_label: 'Causalidad sin respaldo',
    description:
      'Afirmar que una cosa causó otra cuando la evidencia sólo respalda correlación, secuencia o intención.',
  },
  {
    key: 'opinion_as_fact',
    label: 'Opinión como hecho',
    polarity: 'lower_is_better',
    low_label: 'Opinión atribuida',
    high_label: 'Opinión presentada como hecho',
    description:
      'Presentar juicios evaluativos o en disputa con la forma gramatical de un reporte factual, sin atribución ni matiz.',
  },
  {
    key: 'source_diversity',
    label: 'Diversidad de fuentes',
    polarity: 'higher_is_better',
    low_label: 'Fuente única',
    high_label: 'Muchas fuentes distintas',
    description:
      'Cuántas fuentes genuinamente distintas y relevantes usa el artículo. Cuenta originales distintos: cinco citas de un mismo briefing son una fuente.',
  },
  {
    key: 'primary_source_grounding',
    label: 'Anclaje en fuente primaria',
    polarity: 'higher_is_better',
    low_label: 'Sin anclaje verificable',
    high_label: 'Anclado y verificable',
    description:
      'Qué tanto las afirmaciones del artículo se anclan en material primario que el lector podría revisar, en vez de en versiones de segunda mano.',
  },
] as const

export interface ImpactAxisMeta {
  key: ImpactAxisKey
  label: string
  /** Spanish name of the negative pole — the first-named half of the key. */
  negative_label: string
  /** Spanish name of the positive pole. */
  positive_label: string
  description: string
}

/**
 * The seven policy-effect axes. These describe effects found in a text. They
 * are NOT party labels, NOT ideological placements, and must never be summed,
 * averaged or projected onto a single left–right dimension.
 */
export const IMPACT_AXES: readonly ImpactAxisMeta[] = [
  {
    key: 'households_vs_firms',
    label: 'Hogares · Empresas',
    negative_label: 'Hogares',
    positive_label: 'Empresas',
    description:
      'Si los efectos identificados recaen principalmente en hogares o en empresas. No dice nada sobre si alguno de los dos es deseable.',
  },
  {
    key: 'redistribution_vs_growth',
    label: 'Redistribución · Crecimiento',
    negative_label: 'Redistribución',
    positive_label: 'Crecimiento',
    description:
      'Si las disposiciones operan cambiando la distribución de recursos o cambiando los incentivos a producir e invertir. Muchos textos hacen ambas cosas.',
  },
  {
    key: 'public_vs_private_provision',
    label: 'Provisión pública · Provisión privada',
    negative_label: 'Provisión pública',
    positive_label: 'Provisión privada',
    description:
      'Si un servicio o función se desplaza hacia la provisión pública o hacia la provisión privada.',
  },
  {
    key: 'worker_protection_vs_flexibility',
    label: 'Protección laboral · Flexibilidad',
    negative_label: 'Protección laboral',
    positive_label: 'Flexibilidad',
    description:
      'Si las reglas de empleo se estrechan hacia la protección o se aflojan hacia la flexibilidad.',
  },
  {
    key: 'environment_vs_project_acceleration',
    label: 'Resguardo ambiental · Aceleración de proyectos',
    negative_label: 'Resguardo ambiental',
    positive_label: 'Aceleración de proyectos',
    description:
      'Si se fortalecen los resguardos ambientales o se acelera la aprobación y ejecución de proyectos.',
  },
  {
    key: 'central_vs_local',
    label: 'Nivel central · Nivel local',
    negative_label: 'Nivel central',
    positive_label: 'Nivel local',
    description:
      'Si la autoridad, los ingresos o la discrecionalidad se mueven hacia el gobierno central o hacia órganos regionales y locales.',
  },
  {
    key: 'current_relief_vs_long_term_investment',
    label: 'Alivio inmediato · Inversión de largo plazo',
    negative_label: 'Alivio inmediato',
    positive_label: 'Inversión de largo plazo',
    description:
      'Si los recursos se dirigen al alivio inmediato o a capacidades construidas en un horizonte más largo.',
  },
] as const

/** The seven warm-stage phases, in execution order. */
export const WARM_PHASES: readonly WarmPhase[] = [
  'document_understanding',
  'proposition_extraction',
  'topic_graph',
  'search_vocabulary',
  'evidence_collection',
  'news_clustering',
  'readiness',
] as const

export const WARM_PHASE_LABELS: Record<WarmPhase, string> = {
  document_understanding: 'Comprensión del documento',
  proposition_extraction: 'Extracción de proposiciones',
  topic_graph: 'Grafo de temas',
  search_vocabulary: 'Vocabulario de búsqueda',
  evidence_collection: 'Recolección de evidencia',
  news_clustering: 'Agrupación de cobertura',
  readiness: 'Suficiencia de evidencia',
}

/**
 * What kind of artefact a source is — which constrains what it can establish.
 * This is not a ranking of trustworthiness and must not be used as one.
 */
export const EVIDENCE_TIER_LABELS: Record<EvidenceTier, string> = {
  primary_document: 'Documento primario',
  legislative_record: 'Registro legislativo',
  official_technical_report: 'Informe técnico oficial',
  statistical_dataset: 'Conjunto de datos estadísticos',
  peer_reviewed: 'Publicación revisada por pares',
  expert_analysis: 'Análisis experto',
  journalism: 'Periodismo',
  political_statement: 'Declaración política',
  social_media: 'Redes sociales',
}

export const INDEPENDENCE_LABELS: Record<Independence, string> = {
  original_reporting: 'Reporteo original',
  syndicated: 'Sindicado',
  derivative: 'Derivado',
  aggregated: 'Agregado',
  unknown: 'Sin determinar',
}

export const READINESS_STATE_LABELS: Record<ReadinessState, string> = {
  insufficient: 'Evidencia insuficiente',
  partial: 'Evidencia parcial',
  ready: 'Evidencia suficiente',
}

export interface ReadinessDimensionMeta {
  key: ReadinessDimensionKey
  label: string
  description: string
}

/** All seven readiness dimensions measure Aleph's evidence, never the document. */
export const READINESS_DIMENSIONS: readonly ReadinessDimensionMeta[] = [
  {
    key: 'document_understanding',
    label: 'Lectura del documento',
    description:
      'Qué tan completamente se leyó el documento fuente: calidad del texto, cobertura de secciones, disposiciones y supuestos extraídos.',
  },
  {
    key: 'primary_source_coverage',
    label: 'Cobertura de fuentes primarias',
    description:
      'Si se recuperaron los documentos, registros y datos oficiales subyacentes, y no sólo comentarios sobre ellos.',
  },
  {
    key: 'news_coverage',
    label: 'Cobertura de prensa',
    description:
      'Volumen y amplitud del reporteo recuperado. No es la dimensión principal: mucha cobertura no es evidencia.',
  },
  {
    key: 'temporal_coverage',
    label: 'Cobertura temporal',
    description:
      'Si la evidencia abarca los períodos que importan: antes y después del documento, y las fechas que sus propias disposiciones fijan.',
  },
  {
    key: 'evidence_diversity',
    label: 'Diversidad de evidencia',
    description:
      'Reparto entre tipos de evidencia: oficial, estadística, académica, periodística y material que contradice al documento.',
  },
  {
    key: 'claim_coverage',
    label: 'Cobertura de afirmaciones',
    description:
      'Proporción de afirmaciones extraídas que tienen alguna evidencia asociada. Las no cubiertas se muestran como no evaluadas.',
  },
  {
    key: 'source_independence',
    label: 'Independencia de fuentes',
    description:
      'Cuánto del material recuperado es observación independiente y no reproducción. Sin esto, la sindicación se lee como corroboración.',
  },
] as const
