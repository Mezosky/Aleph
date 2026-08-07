"""Controlled vocabularies shared by every Aleph schema, model and consumer.

Aleph's central epistemic commitment is that the *shape* of a judgement should be
fixed before any particular judgement is made. If the set of possible verdicts,
evidence tiers or framing dimensions could be extended at the moment of writing a
result, then a result could always be made to fit whatever conclusion was
convenient: a claim that survived no check could be given a new, flattering
verdict label; a document that scored badly on a fixed axis could be described on
a freshly-invented one. Enumerating these vocabularies once, here, and forbidding
anything outside them downstream is what makes two analyses comparable and what
makes a bad result visible as a bad result rather than as a different kind of
result.

Three of the vocabularies encode refusals rather than answers, and they matter
more than the rest:

* :class:`Verdict` contains ``not_a_factual_claim`` and ``forecast_conditional``
  so that an opinion or a prediction is never forced into a true/false frame.
* :class:`ReadinessState` contains ``insufficient`` so the pipeline can decline
  to publish rather than manufacture a confident answer over thin evidence.
* :class:`EvidenceStrength` contains ``insufficient`` for the same reason at the
  level of a single question.

Two absences are equally deliberate. There is no vocabulary here for political
leaning, party, credibility, prestige or trust; :class:`EvidenceTier` describes
*what kind of artefact* a source is, and therefore what it can establish, never
how much it should be believed. And nothing in this module names a jurisdiction,
an institution or a document: Aleph is document-agnostic, and jurisdiction
specifics live in registry and data files only.

Every value is lowercase ``snake_case`` and matches the corresponding JSON Schema
enum in ``/schemas`` character for character. Changing a value here is a breaking
change to the published data contract.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    # --- common.json ---------------------------------------------------------
    "DataStatus",
    "Polarity",
    "StatementType",
    "Verdict",
    "EvidenceStrength",
    "EvidenceTier",
    "Direction",
    "Magnitude",
    "TimeHorizon",
    "Causality",
    "ReadinessState",
    "Independence",
    "WarmPhase",
    "MoneyUnit",
    "QuantityKind",
    "ProvenanceSourceKind",
    "ConfidenceFactor",
    "ConfidenceEffect",
    "UncertaintyKind",
    # --- document.json -------------------------------------------------------
    "JurisdictionLevel",
    "AuthorshipEntityKind",
    "DocumentType",
    "DocumentStatus",
    "ExtractionQualityState",
    "HashAlgorithm",
    "RetrievalMethod",
    "ExtractionMethod",
    "SectionType",
    "ProvisionType",
    "MechanismType",
    "MonetaryRole",
    "Recurrence",
    "QuantityRole",
    "AssumptionType",
    "CitationTargetKind",
    "AmendmentOperation",
    "DependencyKind",
    "DependencyStatus",
    "InstitutionRole",
    "ExtractionWarningCode",
    "WarningSeverity",
    # --- proposition.json ----------------------------------------------------
    "PropositionType",
    "Modality",
    # --- topic_graph.json ----------------------------------------------------
    "NodeKind",
    "EdgeKind",
    "EdgeBasis",
    # --- search_vocabulary.json ----------------------------------------------
    "TargetSourceType",
    "QuerySyntax",
    "TermSource",
    # --- claim.json ----------------------------------------------------------
    "EpistemicCheck",
    "CheckOutcome",
    "WithheldCategory",
    "HistoricalConsistencyAssessment",
    "RhetoricalPattern",
    # --- news_article.json ---------------------------------------------------
    "ArticleType",
    "GroundingKind",
    # --- news_cluster.json ---------------------------------------------------
    "ClusterKind",
    "ChainKind",
    "SharedOriginKind",
    # --- framing_profile.json ------------------------------------------------
    "FramingDimensionKey",
    # --- impact_map.json -----------------------------------------------------
    "ImpactAxisKey",
    "GroupKind",
    # --- contradiction.json --------------------------------------------------
    "Stance",
    # --- neutrality_report.json ----------------------------------------------
    "PerturbationKind",
    # --- readiness.json ------------------------------------------------------
    "ReadinessDimensionKey",
    "GapSeverity",
    "MissingKind",
    "PhaseState",
    # --- source_registry.json ------------------------------------------------
    "SourceKind",
    "FeedFormat",
    "Paywall",
    # --- analysis_bundle.json ------------------------------------------------
    "TimelineEventKind",
    # --- operational (not part of the published data contract) ---------------
    "RetrievalMode",
    "LLMProviderName",
    # --- ordered tuples ------------------------------------------------------
    "WARM_PHASE_ORDER",
    "FRAMING_DIMENSION_KEYS",
    "IMPACT_AXIS_KEYS",
    "PERTURBATION_KINDS",
    "EPISTEMIC_CHECKS",
    "READINESS_DIMENSION_KEYS",
]


# ---------------------------------------------------------------------------
# common.json
# ---------------------------------------------------------------------------


class DataStatus(StrEnum):
    """Provenance status of a whole dataset.

    ``synthetic`` is load-bearing product behaviour, not a technical flag: a
    synthetic bundle describes no real statement by any real person or outlet,
    and every interface is required to say so where a reader will see it.
    """

    SYNTHETIC = "synthetic"
    DERIVED = "derived"
    PARTIAL = "partial"
    STALE = "stale"


class Polarity(StrEnum):
    """How to read a 0-100 score.

    Carried next to every score so no interface has to guess whether a high
    number is a merit or a fault. Heavy loaded language and strong primary-source
    grounding are both high numbers and mean opposite things.
    """

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    NEUTRAL = "neutral"


class StatementType(StrEnum):
    """What kind of utterance a statement is.

    Determines which epistemic checks apply. An opinion graded as if it were a
    checkable fact is a category error, and this vocabulary exists to make that
    error impossible to commit silently.
    """

    FACT = "fact"
    INTERPRETATION = "interpretation"
    FORECAST = "forecast"
    OPINION = "opinion"
    NORMATIVE = "normative"


class Verdict(StrEnum):
    """Outcome of a speaker-blind factual evaluation.

    ``not_a_factual_claim`` and ``forecast_conditional`` are the honest exits:
    without them, every opinion and every prediction would be forced into a
    true/false frame it does not belong in.
    """

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"
    NOT_A_FACTUAL_CLAIM = "not_a_factual_claim"
    FORECAST_CONDITIONAL = "forecast_conditional"


class EvidenceStrength(StrEnum):
    """How much weight assembled evidence can bear for one specific question.

    A property of the (evidence, question) pair, never of the publisher's
    standing. ``insufficient`` is a real and publishable result.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class EvidenceTier(StrEnum):
    """The kind of artefact an evidence item is.

    Tier constrains what a source can establish. It is NOT a credibility ranking
    and must never be used as an authority shortcut: a primary document
    establishes what a text says, not whether its projections will hold; a
    political statement is strong evidence that something was said and weak
    evidence that it is true.
    """

    PRIMARY_DOCUMENT = "primary_document"
    LEGISLATIVE_RECORD = "legislative_record"
    OFFICIAL_TECHNICAL_REPORT = "official_technical_report"
    STATISTICAL_DATASET = "statistical_dataset"
    PEER_REVIEWED = "peer_reviewed"
    EXPERT_ANALYSIS = "expert_analysis"
    JOURNALISM = "journalism"
    POLITICAL_STATEMENT = "political_statement"
    SOCIAL_MEDIA = "social_media"


class Direction(StrEnum):
    """Sign of an estimated effect on a group or quantity."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    UNCERTAIN = "uncertain"
    NONE = "none"


class Magnitude(StrEnum):
    """Coarse size of an estimated effect.

    Deliberately coarse: a numeric effect size would assert a precision the
    underlying text usually does not support.
    """

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    UNKNOWN = "unknown"


class TimeHorizon(StrEnum):
    """When an effect is expected to be felt."""

    IMMEDIATE = "immediate"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"
    UNKNOWN = "unknown"


class Causality(StrEnum):
    """Whether an effect follows directly or through an intermediate mechanism."""

    DIRECT = "direct"
    INDIRECT = "indirect"
    UNKNOWN = "unknown"


class ReadinessState(StrEnum):
    """Whether Aleph has collected enough context to publish verdicts at all."""

    INSUFFICIENT = "insufficient"
    PARTIAL = "partial"
    READY = "ready"


class Independence(StrEnum):
    """Whether an item is an independent observation or a restatement.

    Ten outlets republishing one wire story are one piece of evidence, not ten.
    """

    ORIGINAL_REPORTING = "original_reporting"
    SYNDICATED = "syndicated"
    DERIVATIVE = "derivative"
    AGGREGATED = "aggregated"
    UNKNOWN = "unknown"


class WarmPhase(StrEnum):
    """One of the seven fixed warm-stage phases run before any evaluation."""

    DOCUMENT_UNDERSTANDING = "document_understanding"
    PROPOSITION_EXTRACTION = "proposition_extraction"
    TOPIC_GRAPH = "topic_graph"
    SEARCH_VOCABULARY = "search_vocabulary"
    EVIDENCE_COLLECTION = "evidence_collection"
    NEWS_CLUSTERING = "news_clustering"
    READINESS = "readiness"


class MoneyUnit(StrEnum):
    """Scale multiplier applied to a monetary amount.

    Aleph never stores a bare number for money; without the multiplier a figure
    cannot be compared with anything.
    """

    UNIT = "unit"
    THOUSAND = "thousand"
    MILLION = "million"
    BILLION = "billion"
    PERCENT_OF_GDP = "percent_of_gdp"


class QuantityKind(StrEnum):
    """What sort of non-monetary number this is.

    ``percentage`` and ``percentage_point`` are distinct because conflating them
    is one of the most common ways a true figure becomes a false statement.
    """

    PERCENTAGE = "percentage"
    PERCENTAGE_POINT = "percentage_point"
    COUNT = "count"
    RATIO = "ratio"
    INDEX = "index"
    RATE = "rate"
    DURATION = "duration"
    OTHER = "other"


class ProvenanceSourceKind(StrEnum):
    """What sort of thing an extracted item came from."""

    DOCUMENT = "document"
    ARTICLE = "article"
    DATASET = "dataset"
    WEBPAGE = "webpage"
    STATEMENT = "statement"
    DERIVED = "derived"


class ConfidenceFactor(StrEnum):
    """A named factor that raised or lowered evidence confidence.

    Naming the factors makes a confidence number arguable. An unexplained
    confidence figure is an assertion about the pipeline's mood.
    """

    PRIMARY_SOURCE_COVERAGE = "primary_source_coverage"
    EVIDENCE_AGREEMENT = "evidence_agreement"
    TEMPORAL_CONSISTENCY = "temporal_consistency"
    QUANTITATIVE_VALIDATION = "quantitative_validation"
    SOURCE_INDEPENDENCE = "source_independence"
    RETRIEVAL_COMPLETENESS = "retrieval_completeness"
    CLAIM_AMBIGUITY = "claim_ambiguity"


class ConfidenceEffect(StrEnum):
    """Direction in which a confidence factor moved the figure."""

    RAISES = "raises"
    LOWERS = "lowers"
    NEUTRAL = "neutral"


class UncertaintyKind(StrEnum):
    """What sort of thing remains unresolved.

    Aleph publishes uncertainties rather than rounding them away; typing them is
    what lets a retrieval planner act on them.
    """

    MISSING_EVIDENCE = "missing_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    MODEL_DEPENDENCY = "model_dependency"
    DEFINITIONAL_AMBIGUITY = "definitional_ambiguity"
    TEMPORAL = "temporal"
    MEASUREMENT = "measurement"
    OUT_OF_SCOPE = "out_of_scope"


# ---------------------------------------------------------------------------
# document.json
# ---------------------------------------------------------------------------


class JurisdictionLevel(StrEnum):
    """Administrative level an instrument operates at.

    A free parameter, not a branch point: library code must never behave
    differently because of a particular jurisdiction.
    """

    SUPRANATIONAL = "supranational"
    NATIONAL = "national"
    SUBNATIONAL = "subnational"
    MUNICIPAL = "municipal"
    SECTORAL = "sectoral"
    UNKNOWN = "unknown"


class AuthorshipEntityKind(StrEnum):
    """What sort of entity is recorded as responsible for a document.

    ``individual_role`` exists so a person can be recorded by function; a
    personal name is stored only when no role is recoverable, and is then
    flagged so redaction can find and strip it.
    """

    INSTITUTION = "institution"
    COMMITTEE = "committee"
    OFFICE = "office"
    WORKING_GROUP = "working_group"
    INDIVIDUAL_ROLE = "individual_role"
    UNKNOWN = "unknown"


class DocumentType(StrEnum):
    """The known set of document kinds.

    Note that ``document.json`` also accepts any other lowercase snake_case
    string, so that an arbitrary PDF passes through the pipeline instead of
    being rejected at the door. Consumers must render an unrecognised value as
    ``other`` rather than failing.
    """

    BILL = "bill"
    LAW = "law"
    DECREE = "decree"
    REGULATION = "regulation"
    FINANCIAL_REPORT = "financial_report"
    TECHNICAL_REPORT = "technical_report"
    BUDGET = "budget"
    RULING = "ruling"
    CONSULTATION = "consultation"
    OTHER = "other"


class DocumentStatus(StrEnum):
    """Lifecycle state of an instrument at retrieval time.

    ``unknown`` is a legitimate and common answer. A claim's evaluation changes
    depending on whether a provision is in force or merely proposed, so guessing
    here would corrupt every downstream verdict.
    """

    DRAFT = "draft"
    PROPOSED = "proposed"
    INTRODUCED = "introduced"
    IN_COMMITTEE = "in_committee"
    PASSED = "passed"
    ENACTED = "enacted"
    IN_FORCE = "in_force"
    AMENDED = "amended"
    SUSPENDED = "suspended"
    REPEALED = "repealed"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"
    PUBLISHED = "published"
    UNKNOWN = "unknown"


class ExtractionQualityState(StrEnum):
    """Coarse verdict on whether extracted text can support fine-grained claims.

    Downstream confidence is capped by this: high model confidence over a badly
    OCRed page is not knowledge.
    """

    GOOD = "good"
    DEGRADED = "degraded"
    POOR = "poor"
    UNKNOWN = "unknown"


class HashAlgorithm(StrEnum):
    """Digest algorithm used to fingerprint retrieved bytes."""

    SHA256 = "sha256"
    SHA512 = "sha512"
    SHA1 = "sha1"
    MD5 = "md5"


class RetrievalMethod(StrEnum):
    """How the source bytes reached Aleph."""

    URL_FETCH = "url_fetch"
    FILE_UPLOAD = "file_upload"
    LOCAL_PATH = "local_path"
    FIXTURE = "fixture"
    UNKNOWN = "unknown"


class ExtractionMethod(StrEnum):
    """How text was recovered from the file.

    Recorded because different extractors produce different character offsets,
    and a span is only meaningful relative to the extractor that produced it.
    """

    PYMUPDF_TEXT = "pymupdf_text"
    PYPDF_TEXT = "pypdf_text"
    OCR = "ocr"
    HTML_DOM = "html_dom"
    PLAIN_TEXT = "plain_text"
    MANUAL = "manual"
    FIXTURE = "fixture"
    OTHER = "other"


class SectionType(StrEnum):
    """Structural role of one node of a document outline."""

    PREAMBLE = "preamble"
    RECITAL = "recital"
    PART = "part"
    TITLE = "title"
    CHAPTER = "chapter"
    ARTICLE = "article"
    CLAUSE = "clause"
    PARAGRAPH = "paragraph"
    ANNEX = "annex"
    SCHEDULE = "schedule"
    TABLE = "table"
    FOOTNOTE = "footnote"
    SIGNATURE_BLOCK = "signature_block"
    OTHER = "other"


class ProvisionType(StrEnum):
    """What a provision does structurally.

    Chosen so downstream code can reason about the kind of effect without
    reading natural language: an obligation and a funding allocation produce
    very different checkable consequences.
    """

    OBLIGATION = "obligation"
    PROHIBITION = "prohibition"
    PERMISSION = "permission"
    ENTITLEMENT = "entitlement"
    BENEFIT = "benefit"
    TAX = "tax"
    FEE = "fee"
    SUBSIDY = "subsidy"
    SANCTION = "sanction"
    FUNDING_ALLOCATION = "funding_allocation"
    INSTITUTIONAL_MANDATE = "institutional_mandate"
    PROCEDURE = "procedure"
    ELIGIBILITY_CRITERION = "eligibility_criterion"
    DEFINITION = "definition"
    TRANSITIONAL = "transitional"
    REPEAL = "repeal"
    AMENDMENT = "amendment"
    DELEGATION = "delegation"
    REPORTING_REQUIREMENT = "reporting_requirement"
    SUNSET = "sunset"
    OTHER = "other"


class MechanismType(StrEnum):
    """How a provision produces its effect.

    Without a stated mechanism an impact claim is unfalsifiable.
    """

    TRANSFER = "transfer"
    TAX_CHANGE = "tax_change"
    PRICE_REGULATION = "price_regulation"
    QUANTITY_REGULATION = "quantity_regulation"
    ELIGIBILITY_CHANGE = "eligibility_change"
    PROCEDURAL_REQUIREMENT = "procedural_requirement"
    INSTITUTIONAL_CREATION = "institutional_creation"
    INFORMATION_REQUIREMENT = "information_requirement"
    ENFORCEMENT = "enforcement"
    FUNDING = "funding"
    MARKET_ENTRY = "market_entry"
    OTHER = "other"


class MonetaryRole(StrEnum):
    """What a monetary figure *is* in its context.

    The same amount can be a cost, a cap or a penalty, and conflating them is a
    standard route to a false summary.
    """

    COST = "cost"
    REVENUE = "revenue"
    ALLOCATION = "allocation"
    TRANSFER = "transfer"
    THRESHOLD = "threshold"
    CAP = "cap"
    FLOOR = "floor"
    PENALTY = "penalty"
    BENEFIT_AMOUNT = "benefit_amount"
    RATE_BASE = "rate_base"
    BASELINE = "baseline"
    PROJECTION = "projection"
    OTHER = "other"


class Recurrence(StrEnum):
    """How often a monetary figure recurs."""

    ONE_OFF = "one_off"
    ANNUAL = "annual"
    MONTHLY = "monthly"
    PER_CASE = "per_case"
    CUMULATIVE = "cumulative"
    UNSPECIFIED = "unspecified"


class QuantityRole(StrEnum):
    """What a non-monetary figure is doing in its context."""

    THRESHOLD = "threshold"
    RATE = "rate"
    TARGET = "target"
    BASELINE = "baseline"
    PROJECTION = "projection"
    COUNT_AFFECTED = "count_affected"
    DURATION = "duration"
    SHARE = "share"
    OTHER = "other"


class AssumptionType(StrEnum):
    """What sort of assumption a document's projection rests on.

    First-class because a forecast is only evaluable against its assumptions: if
    the document assumed a growth path that did not occur, the forecast was not
    thereby wrong, and Aleph must be able to say so precisely.
    """

    MACROECONOMIC = "macroeconomic"
    BEHAVIOURAL = "behavioural"
    DEMOGRAPHIC = "demographic"
    TAKE_UP = "take_up"
    COMPLIANCE = "compliance"
    PRICE = "price"
    IMPLEMENTATION = "implementation"
    BASELINE = "baseline"
    ADMINISTRATIVE_CAPACITY = "administrative_capacity"
    EXTERNAL_CONDITION = "external_condition"
    OTHER = "other"


class CitationTargetKind(StrEnum):
    """What sort of thing a document cites."""

    STATUTE = "statute"
    REGULATION = "regulation"
    CASE = "case"
    DATASET = "dataset"
    REPORT = "report"
    ARTICLE = "article"
    TREATY = "treaty"
    STANDARD = "standard"
    INTERNAL = "internal"
    OTHER = "other"


class AmendmentOperation(StrEnum):
    """The textual operation an amendment performs on another instrument."""

    INSERT = "insert"
    REPLACE = "replace"
    DELETE = "delete"
    RENUMBER = "renumber"
    REPEAL = "repeal"
    EXTEND = "extend"
    SUSPEND = "suspend"
    SUBSTITUTE = "substitute"
    OTHER = "other"


class DependencyKind(StrEnum):
    """What a provision needs from outside itself in order to operate.

    Unmet dependencies are the most common reason a provision that exists has no
    effect, and any impact statement that ignores them overstates the document.
    """

    REQUIRES_ENACTMENT = "requires_enactment"
    REQUIRES_REGULATION = "requires_regulation"
    REQUIRES_APPROPRIATION = "requires_appropriation"
    REQUIRES_RATIFICATION = "requires_ratification"
    CONDITIONED_ON_EVENT = "conditioned_on_event"
    CONFLICTS_WITH = "conflicts_with"
    SUPERSEDES = "supersedes"
    REFERENCES = "references"


class DependencyStatus(StrEnum):
    """Whether a dependency is satisfied, as far as the document itself states.

    ``unknown`` when the document is silent. Aleph does not infer satisfaction.
    """

    MET = "met"
    UNMET = "unmet"
    PARTIALLY_MET = "partially_met"
    UNKNOWN = "unknown"


class InstitutionRole(StrEnum):
    """The role a document assigns to an institution."""

    IMPLEMENTING = "implementing"
    FUNDING = "funding"
    SUPERVISING = "supervising"
    REPORTING = "reporting"
    CONSULTED = "consulted"
    BENEFICIARY = "beneficiary"
    REGULATED = "regulated"
    CREATED = "created"
    ABOLISHED = "abolished"
    OTHER = "other"


class ExtractionWarningCode(StrEnum):
    """A recorded limitation of one reading of a document.

    Published rather than suppressed: a reader is entitled to know that page 42
    was an unreadable scan before trusting a figure said to be on page 42.
    """

    LOW_TEXT_QUALITY = "low_text_quality"
    OCR_USED = "ocr_used"
    MISSING_PAGES = "missing_pages"
    TABLE_EXTRACTION_FAILED = "table_extraction_failed"
    ENCRYPTED_FILE = "encrypted_file"
    TRUNCATED_TEXT = "truncated_text"
    AMBIGUOUS_NUMBERING = "ambiguous_numbering"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    MIXED_LANGUAGES = "mixed_languages"
    SCANNED_IMAGES_ONLY = "scanned_images_only"
    CURRENCY_AMBIGUOUS = "currency_ambiguous"
    DATE_AMBIGUOUS = "date_ambiguous"
    NUMBER_FORMAT_AMBIGUOUS = "number_format_ambiguous"
    SECTION_HEURISTIC_FALLBACK = "section_heuristic_fallback"
    PROVISION_BOUNDARY_UNCERTAIN = "provision_boundary_uncertain"
    OTHER = "other"


class WarningSeverity(StrEnum):
    """How much an extraction warning constrains publication.

    ``error`` means downstream results derived from the affected material must
    not be published without review.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# ---------------------------------------------------------------------------
# proposition.json
# ---------------------------------------------------------------------------


class PropositionType(StrEnum):
    """What kind of statement a proposition is, which fixes how it may be checked.

    ``conditional`` propositions hold only if their antecedent holds and must
    never be reported as unconditional claims; ``assumption`` propositions are
    inputs a document takes as given and are the yardstick a forecast is judged
    against, not facts about the world.
    """

    ASSERTION_OF_CONTENT = "assertion_of_content"
    QUANTITATIVE = "quantitative"
    TEMPORAL = "temporal"
    PROCEDURAL = "procedural"
    CONDITIONAL = "conditional"
    DEFINITIONAL = "definitional"
    ASSUMPTION = "assumption"


class Modality(StrEnum):
    """The force with which a document states something.

    Distinguishing 'shall' from 'may' from 'is expected to' is the difference
    between a duty, a discretion and a projection; collapsing them misreports
    the instrument.
    """

    ASSERTED = "asserted"
    OBLIGATORY = "obligatory"
    PERMISSIVE = "permissive"
    PROHIBITIVE = "prohibitive"
    CONDITIONAL = "conditional"
    HYPOTHETICAL = "hypothetical"
    REPORTED = "reported"
    PROPOSED = "proposed"


# ---------------------------------------------------------------------------
# topic_graph.json
# ---------------------------------------------------------------------------


class NodeKind(StrEnum):
    """What sort of entity a topic-graph node is.

    ``person_role`` is deliberately a ROLE and never a named individual: the
    factual path must be structurally unable to see personal identity, and a
    graph node holding a person's name would defeat that.
    """

    POLICY = "policy"
    PERSON_ROLE = "person_role"
    INSTITUTION = "institution"
    COMPANY = "company"
    SECTOR = "sector"
    SOCIAL_GROUP = "social_group"
    TAX = "tax"
    RIGHT = "right"
    BENEFIT = "benefit"
    OBLIGATION = "obligation"
    FISCAL_EFFECT = "fiscal_effect"
    REGION = "region"
    DATE = "date"
    PROVISION = "provision"


class EdgeKind(StrEnum):
    """The relation a topic-graph edge asserts.

    ``assumes`` is included because a policy that depends on an assumed
    behaviour has a load-bearing link that ordinary impact vocabularies omit,
    and that link is exactly what fails first. ``benefits`` and ``costs`` record
    incidence, not endorsement.
    """

    BENEFITS = "benefits"
    COSTS = "costs"
    REGULATES = "regulates"
    FUNDS = "funds"
    TAXES = "taxes"
    REPLACES = "replaces"
    MODIFIES = "modifies"
    RESTRICTS = "restricts"
    EXPANDS = "expands"
    ASSUMES = "assumes"
    AFFECTS = "affects"
    DEPENDS_ON = "depends_on"


class EdgeBasis(StrEnum):
    """Where a relation came from.

    Interfaces MUST distinguish these: presenting an inferred edge as something
    the document said would misattribute Aleph's reasoning to the source.
    """

    DOCUMENT_EXPLICIT = "document_explicit"
    DOCUMENT_IMPLICIT = "document_implicit"
    INFERRED = "inferred"
    EXTERNAL_EVIDENCE = "external_evidence"


# ---------------------------------------------------------------------------
# search_vocabulary.json
# ---------------------------------------------------------------------------


class TargetSourceType(StrEnum):
    """The kind of source a generated query is aimed at.

    Queries are typed by target because a single generic query silently
    over-collects journalism and under-collects primary documents, which then
    distorts every downstream diversity and independence measure. Note that
    query generation targets SOURCE TYPES and never positions.
    """

    NEWS_OUTLET = "news_outlet"
    GOVERNMENT_BODY = "government_body"
    STATISTICS_AGENCY = "statistics_agency"
    LEGISLATURE = "legislature"
    ACADEMIC = "academic"
    NGO = "ngo"
    AGGREGATOR = "aggregator"
    SEARCH_ENGINE = "search_engine"
    SOCIAL_MEDIA = "social_media"
    ANY = "any"


class QuerySyntax(StrEnum):
    """How a retrieval provider should interpret a query string."""

    PLAIN = "plain"
    PHRASE = "phrase"
    BOOLEAN = "boolean"
    SITE_SCOPED = "site_scoped"
    API_PARAMS = "api_params"


class TermSource(StrEnum):
    """How a retrieval term was derived.

    A phrase lifted from a heading is evidence about the document; a
    model-expanded synonym is a guess. A vocabulary built mostly from guesses
    should be treated as weaker.
    """

    TITLE = "title"
    HEADING = "heading"
    ENTITY = "entity"
    IDENTIFIER = "identifier"
    PROVISION_HEADING = "provision_heading"
    DEFINITION = "definition"
    ABBREVIATION_EXPANSION = "abbreviation_expansion"
    SYNONYM_EXPANSION = "synonym_expansion"
    TRANSLATION = "translation"
    MODEL_EXPANSION = "model_expansion"
    REGISTRY = "registry"
    MANUAL = "manual"


# ---------------------------------------------------------------------------
# claim.json
# ---------------------------------------------------------------------------


class EpistemicCheck(StrEnum):
    """One of the ten criteria applied to every factual claim.

    Fixed so that two claims are always judged against the same list, and so a
    reader can see which tests a verdict actually survived rather than which
    tests happened to be convenient.
    """

    DIRECT_TEXTUAL_EVIDENCE = "direct_textual_evidence"
    DATA_CONSISTENCY = "data_consistency"
    QUANTITATIVE_CORRECTNESS = "quantitative_correctness"
    LOGICAL_VALIDITY = "logical_validity"
    CAUSAL_SUPPORT = "causal_support"
    UNCERTAINTY_HANDLING = "uncertainty_handling"
    CONTEXT_COMPLETENESS = "context_completeness"
    TEMPORAL_CORRECTNESS = "temporal_correctness"
    INDEPENDENT_CORROBORATION = "independent_corroboration"
    CONTRADICTION_WITH_STRONGER_EVIDENCE = "contradiction_with_stronger_evidence"


class CheckOutcome(StrEnum):
    """Outcome of one epistemic check.

    ``na`` is a first-class result: applying a causal-support test to a
    definitional statement would manufacture a failure.
    """

    PASS = "pass"
    FAIL = "fail"
    NA = "na"


class WithheldCategory(StrEnum):
    """A category of attribution removed before a blind factual evaluation.

    These are exactly the inputs Aleph considers irrelevant to whether a
    statement is true. A blind evaluation that withheld nothing is not blind.
    """

    SPEAKER_NAME = "speaker_name"
    SPEAKER_ROLE = "speaker_role"
    PARTY = "party"
    COALITION = "coalition"
    GOVERNMENT_OR_OPPOSITION_STATUS = "government_or_opposition_status"
    OUTLET = "outlet"
    OUTLET_PRESTIGE = "outlet_prestige"
    AUTHOR = "author"
    PUBLICATION_VENUE = "publication_venue"
    INSTITUTIONAL_AFFILIATION = "institutional_affiliation"


class HistoricalConsistencyAssessment(StrEnum):
    """How a claim sits with the same actor's earlier public statements.

    Descriptive context only. An actor who changed position may have changed it
    because the evidence changed, so inconsistency never alters a verdict.
    """

    CONSISTENT = "consistent"
    SHIFTED = "shifted"
    CONTRADICTS_PRIOR = "contradicts_prior"
    INSUFFICIENT_HISTORY = "insufficient_history"
    NOT_ASSESSED = "not_assessed"


class RhetoricalPattern(StrEnum):
    """A named pattern in how a claim was expressed.

    Naming a rhetorical pattern is not a refutation: a claim delivered with
    urgency framing may still be true. Recorded only after the verdict is fixed.
    """

    APPEAL_TO_AUTHORITY = "appeal_to_authority"
    FALSE_DILEMMA = "false_dilemma"
    CHERRY_PICKED_STATISTIC = "cherry_picked_statistic"
    ANECDOTE_AS_EVIDENCE = "anecdote_as_evidence"
    UNFALSIFIABLE_PREDICTION = "unfalsifiable_prediction"
    STRAW_MAN = "straw_man"
    LOADED_COMPARISON = "loaded_comparison"
    URGENCY_FRAMING = "urgency_framing"
    MORAL_FRAMING = "moral_framing"
    TECHNICAL_OBFUSCATION = "technical_obfuscation"
    NONE_DETECTED = "none_detected"


# ---------------------------------------------------------------------------
# news_article.json
# ---------------------------------------------------------------------------


class ArticleType(StrEnum):
    """What kind of published item this is.

    An editorial argues a position and is not evidence that the position is
    correct; a press release is a party's own account of itself; a wire item is
    one observation many outlets may republish without adding independence.
    Aggregating these as if interchangeable is a category error.
    """

    NEWS_REPORT = "news_report"
    ANALYSIS = "analysis"
    OPINION_COLUMN = "opinion_column"
    EDITORIAL = "editorial"
    INTERVIEW = "interview"
    FACT_CHECK = "fact_check"
    PRESS_RELEASE = "press_release"
    WIRE = "wire"


class GroundingKind(StrEnum):
    """How firmly an article anchors a statement in a primary source.

    ``named_without_link`` asks the reader to take the outlet's word for what a
    report says, which is exactly the substitution of authority for evidence
    Aleph refuses to make.
    """

    QUOTED_DIRECTLY = "quoted_directly"
    LINKED = "linked"
    PARAPHRASED = "paraphrased"
    NAMED_WITHOUT_LINK = "named_without_link"
    NONE = "none"


# ---------------------------------------------------------------------------
# news_cluster.json
# ---------------------------------------------------------------------------


class ClusterKind(StrEnum):
    """What holds the members of a cluster together."""

    STORY_CLUSTER = "story_cluster"
    CLAIM_CLUSTER = "claim_cluster"
    REFORM_COMPONENT = "reform_component"
    EVENT = "event"


class ChainKind(StrEnum):
    """How a downstream item came to reproduce an original."""

    WIRE_REDISTRIBUTION = "wire_redistribution"
    PRESS_RELEASE_PICKUP = "press_release_pickup"
    VERBATIM_REUSE = "verbatim_reuse"
    TRANSLATION = "translation"
    AGGREGATION = "aggregation"
    UNKNOWN = "unknown"


class SharedOriginKind(StrEnum):
    """A concrete observation suggesting several items derive from one source.

    ``shared_error`` is the strongest signal of all: independent observers do
    not make the same mistake.
    """

    IDENTICAL_PHRASING = "identical_phrasing"
    IDENTICAL_QUOTE_SET = "identical_quote_set"
    SAME_WIRE_SLUG = "same_wire_slug"
    SAME_PRESS_RELEASE = "same_press_release"
    SAME_DATASET_RELEASE = "same_dataset_release"
    SAME_PUBLICATION_MINUTE = "same_publication_minute"
    SHARED_ERROR = "shared_error"


# ---------------------------------------------------------------------------
# framing_profile.json
# ---------------------------------------------------------------------------


class FramingDimensionKey(StrEnum):
    """The eight fixed framing dimensions.

    These eight numbers must NEVER be collapsed into a single 'bias' or
    'political leaning' score: a scalar would hide the fact that heavy loaded
    language and excellent primary-source grounding are different properties
    pointing in different directions, and would inevitably be read as a
    left-right placement, which Aleph does not produce.

    The first six are ``lower_is_better``; the last two are ``higher_is_better``.
    """

    SELECTION_ASYMMETRY = "selection_asymmetry"
    LOADED_LANGUAGE = "loaded_language"
    CONTEXT_OMISSION = "context_omission"
    CERTAINTY_INFLATION = "certainty_inflation"
    UNSUPPORTED_CAUSAL_LANGUAGE = "unsupported_causal_language"
    OPINION_AS_FACT = "opinion_as_fact"
    SOURCE_DIVERSITY = "source_diversity"
    PRIMARY_SOURCE_GROUNDING = "primary_source_grounding"


# ---------------------------------------------------------------------------
# impact_map.json
# ---------------------------------------------------------------------------


class ImpactAxisKey(StrEnum):
    """The seven fixed policy-effect axes.

    THESE ARE NOT PARTY LABELS. They describe where effects found in a text
    fall, and must never be summed, averaged or projected onto a single
    left-right dimension. Negative always means the first-named pole. The same
    score is compatible with any political sponsorship.
    """

    HOUSEHOLDS_VS_FIRMS = "households_vs_firms"
    REDISTRIBUTION_VS_GROWTH = "redistribution_vs_growth"
    PUBLIC_VS_PRIVATE_PROVISION = "public_vs_private_provision"
    WORKER_PROTECTION_VS_FLEXIBILITY = "worker_protection_vs_flexibility"
    ENVIRONMENT_VS_PROJECT_ACCELERATION = "environment_vs_project_acceleration"
    CENTRAL_VS_LOCAL = "central_vs_local"
    CURRENT_RELIEF_VS_LONG_TERM_INVESTMENT = "current_relief_vs_long_term_investment"


class GroupKind(StrEnum):
    """Canonical groups that may gain from or bear the cost of a document.

    The impact-map schema keeps this vocabulary OPEN — jurisdictions have groups
    Aleph cannot enumerate in advance — so these values are the preferred set,
    not an exhaustive one. Prefer ``specific_industry`` plus a ``group_detail``
    over inventing an industry key.
    """

    LOW_INCOME_HOUSEHOLDS = "low_income_households"
    MIDDLE_INCOME_HOUSEHOLDS = "middle_income_households"
    HIGH_INCOME_HOUSEHOLDS = "high_income_households"
    WORKERS = "workers"
    PENSIONERS = "pensioners"
    STUDENTS = "students"
    MUNICIPALITIES = "municipalities"
    SMES = "smes"
    LARGE_COMPANIES = "large_companies"
    FOREIGN_INVESTORS = "foreign_investors"
    DOMESTIC_INVESTORS = "domestic_investors"
    PROPERTY_OWNERS = "property_owners"
    RENTERS = "renters"
    CENTRAL_GOVERNMENT = "central_government"
    REGIONAL_GOVERNMENTS = "regional_governments"
    FUTURE_TAXPAYERS = "future_taxpayers"
    ENVIRONMENT = "environment"
    SPECIFIC_INDUSTRY = "specific_industry"


# ---------------------------------------------------------------------------
# contradiction.json
# ---------------------------------------------------------------------------


class Stance(StrEnum):
    """How a position relates to the single question at issue.

    ``not_responsive`` is important and common: an actor who answers a different
    question has not contradicted anyone, and recording that prevents Aleph from
    inventing a disagreement out of two people talking past each other.
    """

    AFFIRMS = "affirms"
    DENIES = "denies"
    QUALIFIED_AFFIRM = "qualified_affirm"
    QUALIFIED_DENY = "qualified_deny"
    REFRAMES = "reframes"
    NOT_RESPONSIVE = "not_responsive"


# ---------------------------------------------------------------------------
# neutrality_report.json
# ---------------------------------------------------------------------------


class PerturbationKind(StrEnum):
    """The six fixed perturbation families.

    Each substitutes something evidentially irrelevant and re-runs the
    evaluation. Every verdict change is by construction a defect. Note that
    ``party_swap`` is the only place in the whole system where party appears at
    all — as a variable being deliberately scrambled, never as an input to a
    verdict.
    """

    SPEAKER_SWAP = "speaker_swap"
    SOURCE_SWAP = "source_swap"
    PARTY_SWAP = "party_swap"
    AUTHORITY_REMOVAL = "authority_removal"
    CLAIM_PARAPHRASE = "claim_paraphrase"
    EVIDENCE_ORDER_SHUFFLE = "evidence_order_shuffle"


# ---------------------------------------------------------------------------
# readiness.json
# ---------------------------------------------------------------------------


class ReadinessDimensionKey(StrEnum):
    """The seven readiness dimensions, all higher_is_better.

    They measure the state of Aleph's own evidence base, never the merits of the
    document or of any actor. Fixed keys rather than an open list, because a
    dimension that could be omitted would be omitted precisely when it scored
    badly, and the absence would read as adequacy.
    """

    DOCUMENT_UNDERSTANDING = "document_understanding"
    PRIMARY_SOURCE_COVERAGE = "primary_source_coverage"
    NEWS_COVERAGE = "news_coverage"
    TEMPORAL_COVERAGE = "temporal_coverage"
    EVIDENCE_DIVERSITY = "evidence_diversity"
    CLAIM_COVERAGE = "claim_coverage"
    SOURCE_INDEPENDENCE = "source_independence"


class GapSeverity(StrEnum):
    """How much a named gap constrains publication."""

    BLOCKING = "blocking"
    MAJOR = "major"
    MINOR = "minor"


class MissingKind(StrEnum):
    """What sort of material is absent.

    Typed so a retrieval planner can act on a gap automatically instead of a
    human reading prose.
    """

    PRIMARY_DOCUMENT = "primary_document"
    OFFICIAL_DATA = "official_data"
    INDEPENDENT_REPORTING = "independent_reporting"
    EXPERT_ANALYSIS = "expert_analysis"
    COUNTER_EVIDENCE = "counter_evidence"
    TIME_PERIOD = "time_period"
    QUANTITATIVE_CHECK = "quantitative_check"
    DOCUMENT_SECTION = "document_section"
    ASSUMPTION_STATEMENT = "assumption_statement"
    TRANSLATION = "translation"
    OTHER = "other"


class PhaseState(StrEnum):
    """Completion state of one warm phase.

    A skipped phase with no note is an unexplained gap and should be treated as
    a failure.
    """

    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# source_registry.json
# ---------------------------------------------------------------------------


class SourceKind(StrEnum):
    """What sort of organisation publishes a registered source.

    Determines which generated queries are routed there and which evidence gaps
    the source can close. A statistics agency and a news outlet answer different
    questions, and neither substitutes for the other. This is emphatically NOT a
    ranking.
    """

    NEWS_OUTLET = "news_outlet"
    GOVERNMENT_BODY = "government_body"
    STATISTICS_AGENCY = "statistics_agency"
    LEGISLATURE = "legislature"
    ACADEMIC = "academic"
    NGO = "ngo"
    AGGREGATOR = "aggregator"


class FeedFormat(StrEnum):
    """Machine-readable entry point format for a source.

    Polling a declared feed is both more complete and less intrusive than
    crawling a site.
    """

    RSS = "rss"
    ATOM = "atom"
    SITEMAP = "sitemap"
    API = "api"
    JSON = "json"
    HTML_INDEX = "html_index"


class Paywall(StrEnum):
    """Access barrier on a source.

    Operationally important: an unreachable source is a coverage gap readiness
    must report rather than absorb.
    """

    NONE = "none"
    METERED = "metered"
    HARD = "hard"
    REGISTRATION = "registration"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# analysis_bundle.json
# ---------------------------------------------------------------------------


class TimelineEventKind(StrEnum):
    """Category of a dated event in a document's life.

    ``statement`` covers a public claim entering the record, which is often the
    point at which a contradiction begins.
    """

    DOCUMENT_PUBLISHED = "document_published"
    DOCUMENT_REVISED = "document_revised"
    COMMITTEE_STAGE = "committee_stage"
    VOTE = "vote"
    AMENDMENT = "amendment"
    OFFICIAL_REPORT = "official_report"
    STATEMENT = "statement"
    MEDIA_EVENT = "media_event"
    IMPLEMENTATION_MILESTONE = "implementation_milestone"
    LEGAL_CHALLENGE = "legal_challenge"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Operational vocabularies
#
# These do not appear in the published JSON Schemas — they govern how a run
# behaves, not what a result means — but they are shared across the API, the
# pipeline and the retrieval layer, so they belong with the other fixed sets.
# ---------------------------------------------------------------------------


class RetrievalMode(StrEnum):
    """Whether outbound network retrieval may happen, and on whose initiative.

    ``manual`` is the default and is a hard constraint, not a preference: under
    it no module may perform an outbound fetch as part of a pipeline run.
    Network access must be reached only through an explicit, deliberate call.
    Silent fetching would make a run irreproducible and would expose sources to
    traffic they never agreed to.
    """

    MANUAL = "manual"
    ON_DEMAND = "on_demand"
    AUTO = "auto"


class LLMProviderName(StrEnum):
    """Which language-model provider implementation to load.

    ``mock`` is deterministic and offline and is the default, so that the whole
    pipeline runs end to end with no credentials and produces the same bundle
    every time.
    """

    MOCK = "mock"
    QWEN = "qwen"


# ---------------------------------------------------------------------------
# Canonical orderings
#
# Tuples rather than sets: the order these are presented in is part of the
# product (phase order is causal, dimension order is how a reader scans them).
# ---------------------------------------------------------------------------

WARM_PHASE_ORDER: tuple[WarmPhase, ...] = (
    WarmPhase.DOCUMENT_UNDERSTANDING,
    WarmPhase.PROPOSITION_EXTRACTION,
    WarmPhase.TOPIC_GRAPH,
    WarmPhase.SEARCH_VOCABULARY,
    WarmPhase.EVIDENCE_COLLECTION,
    WarmPhase.NEWS_CLUSTERING,
    WarmPhase.READINESS,
)

FRAMING_DIMENSION_KEYS: tuple[FramingDimensionKey, ...] = tuple(FramingDimensionKey)

IMPACT_AXIS_KEYS: tuple[ImpactAxisKey, ...] = tuple(ImpactAxisKey)

PERTURBATION_KINDS: tuple[PerturbationKind, ...] = tuple(PerturbationKind)

EPISTEMIC_CHECKS: tuple[EpistemicCheck, ...] = tuple(EpistemicCheck)

READINESS_DIMENSION_KEYS: tuple[ReadinessDimensionKey, ...] = tuple(ReadinessDimensionKey)
