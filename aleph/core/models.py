"""Pydantic mirrors of the Aleph data contract, and the types that enforce it.

Every class here corresponds to an object in ``/schemas``, field for field and
enum value for enum value. That correspondence is the point: the JSON Schemas are
what the frontend, the API and any external consumer are written against, and a
Python model that drifts from them turns a contract into a suggestion. All models
are ``extra='forbid'``, mirroring ``additionalProperties: false``, so a typo'd
field name fails at construction rather than vanishing on export.

Three of the rules encoded here are product rules rather than data-shape rules,
and they are worth reading before using this module.

**1. Speaker-blindness is a type, not a convention.**
:class:`RedactedClaimContext` is the *only* thing the blind evaluator may
receive. It is frozen, it forbids extra fields, and it has no property in which a
speaker, party, coalition, government-or-opposition status or outlet could be
written — so the factual path is structurally incapable of seeing them, and no
future edit can quietly reintroduce one without deleting a class that exists
solely to prevent it. :class:`Claim` correspondingly has no top-level verdict:
the verdict lives inside :class:`BlindEvaluation` and there is nowhere for the
attributed, identity-aware pass to overwrite it.

**2. No score exists without its components.**
:class:`ImpactAxis`, :class:`FramingDimension`, :class:`ReadinessDimension` and
:class:`NeutralityReport` all validate that a non-zero score arrives with a
non-empty ``components`` array. A number a reader cannot open is an assertion
dressed as a measurement, so these models raise rather than accept one.

**3. Evidence confidence and model confidence are different quantities.**
:class:`Confidence` keeps them apart and makes only ``evidence_confidence``
required. High model confidence over thin evidence is not reassurance and must
never be presented as though it were.

Nothing in this module names a jurisdiction, an institution, a party or a
document. Money is always structured; dates are always ISO-8601 with UTC
timestamps; ids always match the shared grammar in :mod:`aleph.core.ids`.

Serialisation note: use :meth:`AlephModel.to_jsonable`, not ``model_dump()``.
The schemas distinguish "optional and absent" from "required and null", and
``to_jsonable`` reproduces that distinction exactly — omitting optional fields
that are ``None`` while preserving required-but-nullable ones.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from enum import Enum
from typing import Annotated, Any, Final, Protocol, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from aleph.core.enums import (
    AmendmentOperation,
    ArticleType,
    AssumptionType,
    AuthorshipEntityKind,
    Causality,
    ChainKind,
    CheckOutcome,
    CitationTargetKind,
    ClusterKind,
    ConfidenceEffect,
    ConfidenceFactor,
    DataStatus,
    DependencyKind,
    DependencyStatus,
    Direction,
    DocumentStatus,
    EdgeBasis,
    EdgeKind,
    EpistemicCheck,
    EvidenceStrength,
    EvidenceTier,
    ExtractionMethod,
    ExtractionQualityState,
    ExtractionWarningCode,
    FeedFormat,
    FramingDimensionKey,
    GapSeverity,
    GroundingKind,
    HashAlgorithm,
    HistoricalConsistencyAssessment,
    ImpactAxisKey,
    Independence,
    InstitutionRole,
    JurisdictionLevel,
    Magnitude,
    MechanismType,
    MissingKind,
    Modality,
    MonetaryRole,
    MoneyUnit,
    NodeKind,
    Paywall,
    PerturbationKind,
    PhaseState,
    Polarity,
    PropositionType,
    ProvenanceSourceKind,
    ProvisionType,
    QuantityKind,
    QuantityRole,
    QuerySyntax,
    ReadinessDimensionKey,
    ReadinessState,
    Recurrence,
    RetrievalMethod,
    RhetoricalPattern,
    SectionType,
    SharedOriginKind,
    SourceKind,
    Stance,
    StatementType,
    TargetSourceType,
    TermSource,
    TimeHorizon,
    TimelineEventKind,
    UncertaintyKind,
    Verdict,
    WarmPhase,
    WarningSeverity,
    WithheldCategory,
)
from aleph.core.ids import (
    FRAMING_ID_PATTERN,
    ID_MAX_LENGTH,
    ID_MIN_LENGTH,
    ID_PATTERN,
    SLUG_PATTERN,
)

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

#: The version of the Aleph data contract these models mirror.
SCHEMA_VERSION: Final[str] = "1.0.0"

SCHEMA_VERSION_PATTERN: Final[str] = r"^[0-9]+\.[0-9]+\.[0-9]+$"
TIMESTAMP_PATTERN: Final[str] = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$"
)
DATE_PATTERN: Final[str] = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
DATE_OR_TIMESTAMP_PATTERN: Final[str] = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z)?$"
)
FILE_HASH_PATTERN: Final[str] = r"^[0-9a-f]{32,128}$"
CURRENCY_PATTERN: Final[str] = r"^[A-Z]{3}$"
OPEN_DOCUMENT_TYPE_PATTERN: Final[str] = r"^[a-z][a-z0-9_]*$"

# ---------------------------------------------------------------------------
# Constrained scalar aliases
#
# These carry the schema's own bounds. Using them rather than bare ``str``/
# ``float`` means an out-of-range confidence or a malformed timestamp is caught
# where it is written, not three phases later where it is unattributable.
# ---------------------------------------------------------------------------

SchemaVersion = Annotated[str, StringConstraints(pattern=SCHEMA_VERSION_PATTERN)]
Timestamp = Annotated[str, StringConstraints(pattern=TIMESTAMP_PATTERN)]
"""Timezone-aware UTC instant, e.g. ``2026-08-07T14:03:00Z``."""

DateStr = Annotated[str, StringConstraints(pattern=DATE_PATTERN)]
"""Plain calendar date, e.g. ``2026-08-07``."""

DateOrTimestamp = Annotated[str, StringConstraints(pattern=DATE_OR_TIMESTAMP_PATTERN)]
"""Either of the above. Used where a source states only a date."""

UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
"""A value in [0,1]. Every confidence in Aleph is one of these."""

Score100 = Annotated[int, Field(ge=0, le=100)]
"""A 0-100 score. Never interpret without the accompanying polarity field."""

BipolarScore = Annotated[int, Field(ge=-100, le=100)]
"""A -100..+100 placement on a named two-poled axis. Negative is the
first-named pole. NOT a left-right political score: no such number exists in
Aleph."""

AlephId = Annotated[
    str,
    StringConstraints(pattern=ID_PATTERN, min_length=ID_MIN_LENGTH, max_length=ID_MAX_LENGTH),
]
DocumentId = Annotated[
    str,
    StringConstraints(pattern=r"^doc:[A-Za-z0-9._:-]+$", max_length=ID_MAX_LENGTH),
]
ProvisionId = Annotated[
    str,
    StringConstraints(pattern=r"^prov:[A-Za-z0-9._:-]+$", max_length=ID_MAX_LENGTH),
]
PropositionId = Annotated[
    str,
    StringConstraints(pattern=r"^prop:[A-Za-z0-9._:-]+$", max_length=ID_MAX_LENGTH),
]
NodeId = Annotated[
    str,
    StringConstraints(pattern=r"^node:[A-Za-z0-9._:-]+$", max_length=ID_MAX_LENGTH),
]
EdgeId = Annotated[
    str,
    StringConstraints(pattern=r"^edge:[A-Za-z0-9._:-]+$", max_length=ID_MAX_LENGTH),
]
SourceEntryId = Annotated[
    str,
    StringConstraints(pattern=r"^src:[A-Za-z0-9._:-]+$", max_length=ID_MAX_LENGTH),
]
FramingProfileId = Annotated[str, StringConstraints(pattern=FRAMING_ID_PATTERN)]
DocumentSlug = Annotated[str, StringConstraints(pattern=SLUG_PATTERN)]
FileHash = Annotated[str, StringConstraints(pattern=FILE_HASH_PATTERN)]
CurrencyCode = Annotated[str, StringConstraints(pattern=CURRENCY_PATTERN)]
NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------


def _encode(value: Any) -> Any:
    """Recursively render a model tree as JSON-safe primitives."""
    if isinstance(value, AlephModel):
        return value.to_jsonable()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list | tuple):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value


class AlephModel(BaseModel):
    """Base for every Aleph model.

    ``extra='forbid'`` mirrors ``additionalProperties: false`` throughout the
    contract. That is not tidiness: several schemas rely on closedness to make a
    prohibition structural rather than advisory — no credibility field can be
    smuggled into a source registry entry, no party field into a blind
    evaluation.

    ``protected_namespaces=()`` is set because the contract genuinely contains
    ``model_confidence`` and ``model_provider``; pydantic's default guard would
    warn on both, and renaming them would break the published contract.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        protected_namespaces=(),
        validate_default=True,
    )

    def to_jsonable(self) -> dict[str, Any]:
        """Render to a mapping that validates against the corresponding schema.

        The schemas draw a distinction ``model_dump()`` cannot express on its
        own: a field that is *optional* must be absent when unset, while a field
        that is *required and nullable* must be present as ``null``. Emitting
        ``"note": null`` where the schema declared a plain string is invalid;
        omitting ``"attributed_analysis"`` where the schema requires the key is
        equally invalid, and would additionally hide the two-stage evaluation
        design that the required key exists to make explicit.

        Because required-in-schema is mirrored exactly by required-in-pydantic
        throughout this module, the rule is simply: keep required fields always,
        drop optional fields that are ``None``.
        """
        out: dict[str, Any] = {}
        for name, info in type(self).model_fields.items():
            value = getattr(self, name)
            if value is None and not info.is_required():
                continue
            out[info.alias or name] = _encode(value)
        return out

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialise via :meth:`to_jsonable`, with stable key order.

        Key order follows field declaration order, which follows the schema, so
        two runs over the same input produce byte-identical output and a diff
        shows what changed in the analysis rather than in the serialiser.
        """
        return json.dumps(self.to_jsonable(), indent=indent, ensure_ascii=False)


def _require_components(score: float | int | None, components: Sequence[Any], what: str) -> None:
    """Raise unless a non-zero score arrives with something a reader can open.

    Aleph's rule is that no metric may exist without the list of contributing
    evidence that produced it. A score of exactly zero is exempt because zero is
    how "no relevant material was found" is expressed, and demanding components
    for an absence would push analysers into inventing them.
    """
    if score and not components:
        raise ValueError(
            f"{what}: a score of {score} was set with an empty components[] list. "
            "Every Aleph score must be inspectable: publish the contributing "
            "factors and their weights, or do not publish the score."
        )


# ---------------------------------------------------------------------------
# common.json
# ---------------------------------------------------------------------------


class Money(AlephModel):
    """A monetary amount, never a bare number.

    Currency, scale multiplier and reference year are all carried because a
    figure without them cannot be compared with anything or checked against
    anything — and an uncheckable figure quoted as fact is exactly the failure
    mode Aleph exists to catch.
    """

    amount: float
    currency: CurrencyCode
    unit: MoneyUnit
    year: Annotated[int, Field(ge=1800, le=2200)] | None = None
    """Reference year for real/constant terms. ``None`` when the source is silent."""
    basis: str | None = None
    """e.g. ``'nominal'``, ``'constant'``, ``'cumulative_10y'``."""


class Quantity(AlephModel):
    """A non-monetary numeric value with its literal source text preserved.

    ``raw_text`` is required so that a decimal-separator or unit misreading is
    auditable rather than inherited silently by everything downstream.
    """

    value: float
    kind: QuantityKind
    unit: str | None = None
    raw_text: str
    """Verbatim substring from the source, before normalisation."""


class Span(AlephModel):
    """A located, quotable region of a source document.

    ``text`` is required and verbatim. An Aleph assertion with no quotable
    passage is not traceable, and an untraceable assertion is not publishable.
    """

    page: Annotated[int, Field(ge=1)] | None = None
    section_id: str | None = None
    char_start: Annotated[int, Field(ge=0)] | None = None
    char_end: Annotated[int, Field(ge=0)] | None = None
    text: str


class Provenance(AlephModel):
    """Where an extracted item came from.

    Every proposition, provision and claim carries one. Provenance is used for
    authenticity and for attributing what an actor officially said — and it is
    deliberately withheld from the blind factual evaluator, which is why
    :class:`RedactedClaimContext` has no field for it.
    """

    source_id: AlephId
    source_kind: ProvenanceSourceKind
    url: str | None = None
    retrieved_at: Timestamp | None = None
    span: Span | None = None
    extractor: str | None = None
    """Component or model version that produced this item, so results can be
    reproduced or invalidated."""


class ConfidenceBasis(AlephModel):
    """One named factor that raised or lowered evidence confidence."""

    factor: ConfidenceFactor
    effect: ConfidenceEffect
    note: str | None = None


class Confidence(AlephModel):
    """Evidence-derived confidence, held apart from model self-report.

    ``evidence_confidence`` is required and is the figure consumers must
    surface. ``model_confidence`` is optional, diagnostic, and must never be the
    headline number: a model that is 0.95 sure over one paywalled headline is
    telling you about itself, not about the world.
    """

    evidence_confidence: UnitInterval
    model_confidence: UnitInterval | None = None
    basis: list[ConfidenceBasis] = Field(default_factory=list)
    limiting_factor: str | None = None
    """The single biggest reason confidence is not higher, stated plainly."""


class Component(AlephModel):
    """One inspectable contributor to a composite score.

    No Aleph score may be published without the full list of its components: a
    user must always be able to open a number and see what produced it.
    """

    label: str
    direction: Direction
    weight: Annotated[float, Field(ge=-100, le=100)]
    """Signed contribution in the score's own units."""
    evidence_refs: list[AlephId] = Field(default_factory=list)
    note: str | None = None


class SourceRef(AlephModel):
    """A pointer to an external source.

    ``tier`` says what kind of artefact it is, and therefore what it can
    establish. There is deliberately no credibility or prestige field: Aleph
    must not let institutional standing substitute for evidential relevance.
    """

    id: AlephId
    title: str
    url: str | None = None
    publisher: str | None = None
    published_at: DateOrTimestamp | None = None
    tier: EvidenceTier
    independence: Independence | None = None
    language: str | None = None


class Uncertainty(AlephModel):
    """An explicit statement of what remains unresolved.

    Aleph publishes these rather than rounding them away. ``resolvable_by`` is
    what turns an admission into a task.
    """

    statement: str
    kind: UncertaintyKind
    resolvable_by: str | None = None


# ---------------------------------------------------------------------------
# document.json  (warm phase 1: document_understanding)
# ---------------------------------------------------------------------------


class PageRange(AlephModel):
    """Inclusive 1-based page interval in the source file."""

    start: Annotated[int, Field(ge=1)]
    end: Annotated[int, Field(ge=1)]


class Jurisdiction(AlephModel):
    """The legal or administrative space a document or source belongs to.

    Free parameters, never a branch point: Aleph's library code must not behave
    differently for a particular jurisdiction. Jurisdiction-specific behaviour
    belongs in registry and data files keyed by these values.
    """

    code: str | None = None
    name: str | None = None
    level: JurisdictionLevel


class DocumentIdentifier(AlephModel):
    """One external identifier for a document under a named scheme.

    A list is used because the same document is routinely known by several
    numbers, and retrieval fails when only one is known.
    """

    scheme: str
    value: str
    issuer: str | None = None


class AuthorshipEntry(AlephModel):
    """Who is responsible for a document, recorded as a ROLE wherever possible.

    Aleph prefers roles to personal names because factual evaluation downstream
    must be blind to individual identity. A personal name is stored only when no
    institutional role is recoverable, and ``is_personal_name`` then flags it so
    redaction can find and strip it before evaluation.
    """

    role: str
    entity_kind: AuthorshipEntityKind
    entity: str | None = None
    is_personal_name: bool = False
    span: Span | None = None


class DocumentDates(AlephModel):
    """Lifecycle dates of a document.

    All nullable because most documents state only some of them, and inventing a
    date would silently fabricate the timeline every later temporal check
    depends on.
    """

    introduced: DateStr | None = None
    published: DateStr | None = None
    retrieved: Timestamp | None = None
    last_amended: DateStr | None = None
    effective_from: DateStr | None = None


class DocumentIdentity(AlephModel):
    """What a document is and where it sits, separable from its contents.

    ``document_type`` accepts any lowercase snake_case value, not only the known
    set, so an arbitrary PDF from any legal system passes through the pipeline
    instead of being rejected at the door.
    """

    slug: DocumentSlug
    title: str
    subtitle: str | None = None
    short_title: str | None = None
    """The name the document is actually referred to by. Often the only name
    under which coverage of it can be found."""
    jurisdiction: Jurisdiction
    institution: str | None = None
    document_type: str
    document_type_raw: str | None = None
    language: str
    additional_languages: list[str] = Field(default_factory=list)
    version: str | None = None
    legislative_identifier: str | None = None
    identifiers: list[DocumentIdentifier] = Field(default_factory=list)
    status: DocumentStatus
    dates: DocumentDates | None = None
    authorship: list[AuthorshipEntry] = Field(default_factory=list)
    summary: str | None = None
    keywords: list[str] = Field(default_factory=list)

    @field_validator("document_type")
    @classmethod
    def _document_type_is_snake_case(cls, value: str) -> str:
        if not re.match(OPEN_DOCUMENT_TYPE_PATTERN, value):
            raise ValueError(
                f"document_type {value!r} must be lowercase snake_case. The vocabulary "
                "is open so any document can pass through, but the shape is fixed so "
                "consumers can normalise an unknown value to 'other'."
            )
        return value


class ExtractionQuality(AlephModel):
    """Measured quality of text extraction.

    Published because downstream confidence must be capped by it: high model
    confidence over a badly-OCRed page is not knowledge.
    """

    state: ExtractionQualityState
    text_coverage: UnitInterval | None = None
    chars_extracted: Annotated[int, Field(ge=0)] | None = None
    pages_without_text: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list)
    ocr_used: bool = False
    ocr_confidence: UnitInterval | None = None
    tables_detected: Annotated[int, Field(ge=0)] | None = None
    note: str | None = None


class DocumentSource(AlephModel):
    """Where the bytes came from and how they became text.

    The hash exists so a later re-run can tell "the analysis changed" apart from
    "the document changed". Without it no result is reproducible.
    """

    url: str | None = None
    file_name: str | None = None
    media_type: str | None = None
    file_hash: FileHash | None = None
    hash_algorithm: HashAlgorithm | None = None
    file_size_bytes: Annotated[int, Field(ge=0)] | None = None
    page_count: Annotated[int, Field(ge=0)] | None = None
    retrieved_at: Timestamp | None = None
    retrieval_method: RetrievalMethod | None = None
    extraction_method: ExtractionMethod
    extractor_version: str | None = None
    """Version of the extraction component, so a span can be invalidated when
    the extractor changes."""
    extraction_quality: ExtractionQuality
    license_note: str | None = None


class Section(AlephModel):
    """One node of a document's outline.

    Recursive, because legal and technical documents nest and a flat page model
    loses the scope of a provision — which is exactly what determines what the
    provision applies to.
    """

    id: str
    number: str | None = None
    """The document's own numbering label, verbatim. A string because numbering
    schemes are not numeric."""
    heading: str
    level: Annotated[int, Field(ge=0)]
    section_type: SectionType | None = None
    page_range: PageRange | None = None
    char_start: Annotated[int, Field(ge=0)] | None = None
    char_end: Annotated[int, Field(ge=0)] | None = None
    provision_ids: list[ProvisionId] = Field(default_factory=list)
    children: list[Section] = Field(default_factory=list)
    is_heuristic: bool = False
    """True when the section was inferred from typography rather than read from
    an explicit heading, so a reader knows the outline is a guess."""


Section.model_rebuild()


class DocumentStructure(AlephModel):
    """A document's outline, held separately from its provisions.

    Kept apart so navigation and citation survive even when provision extraction
    is incomplete.
    """

    sections: list[Section] = Field(default_factory=list)
    numbering_scheme: str | None = None
    max_depth: Annotated[int, Field(ge=0)] | None = None
    has_table_of_contents: bool = False


class Provision(AlephModel):
    """A single operative unit of a document: one thing the instrument does.

    Provisions are the atoms that impact analysis, claim checking and the topic
    graph all point back to, which is why each carries a verbatim span, its own
    effective and sunset dates, and an explicit mechanism rather than an inferred
    intent. ``exceptions`` is recorded explicitly because omitting a carve-out is
    one of the most common ways a summary becomes false.
    """

    id: ProvisionId
    title: str | None = None
    text: str
    provision_type: ProvisionType
    section_id: str | None = None
    span: Span
    effective_date: DateStr | None = None
    effective_condition: str | None = None
    sunset_date: DateStr | None = None
    amends: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    implementing_body: str | None = None
    """Institution charged with carrying the provision out. Never an individual."""
    mechanism: str | None = None
    """HOW the provision produces its effect, drawn from the text. Without it an
    attributed effect is unfalsifiable."""
    mechanism_type: MechanismType | None = None
    conditions: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    monetary_value_ids: list[str] = Field(default_factory=list)
    quantity_ids: list[str] = Field(default_factory=list)
    deadline_ids: list[str] = Field(default_factory=list)
    affected_institutions: list[str] = Field(default_factory=list)
    affected_populations: list[str] = Field(default_factory=list)
    affected_industries: list[str] = Field(default_factory=list)
    affected_regions: list[str] = Field(default_factory=list)
    """Empty means the document did not restrict scope geographically, NOT that
    scope is universal."""
    confidence: Confidence | None = None


class Definition(AlephModel):
    """A term a document defines for its own purposes.

    Recorded separately because a document's private definition of a common word
    ('household', 'small enterprise') frequently drives disputes about what it
    does. ``scope`` is carried because one instrument may define a word twice.
    """

    id: str
    term: str
    definition_text: str
    scope: str | None = None
    span: Span
    provision_id: str | None = None


class MonetaryValue(AlephModel):
    """One monetary figure in context.

    ``role`` matters more than the number: the same amount can be a cost, a cap
    or a penalty, and conflating them is a standard route to a false summary.
    """

    id: str
    label: str
    money: Money
    role: MonetaryRole
    recurrence: Recurrence | None = None
    fiscal_years: list[Annotated[int, Field(ge=1800, le=2200)]] = Field(default_factory=list)
    is_estimate: bool = False
    """True when the document presents the figure as a projection. A projected
    figure must never be reported as if it were settled."""
    provision_id: str | None = None
    span: Span


class QuantityMention(AlephModel):
    """A non-monetary figure in context, with verbatim source text preserved."""

    id: str
    label: str
    quantity: Quantity
    role: QuantityRole | None = None
    provision_id: str | None = None
    span: Span


class Deadline(AlephModel):
    """An obligation with a time bound.

    The checkable spine of implementation: deadlines are what make a later "was
    this done on time?" question answerable. ``consequence_of_missing`` is
    frequently empty, and recording that silence is itself informative.
    """

    id: str
    label: str
    date: DateStr | None = None
    relative_period: str | None = None
    trigger: str | None = None
    obligated_party: str | None = None
    consequence_of_missing: str | None = None
    provision_id: str | None = None
    span: Span


class Assumption(AlephModel):
    """A stated assumption underlying a document's own projections.

    First-class because a forecast can only be evaluated against its
    assumptions: if the document assumed a growth path and the growth path did
    not occur, the forecast was not thereby wrong, and Aleph must be able to say
    so precisely. ``is_explicit`` distinguishes what the document said from what
    Aleph inferred from a calculation.
    """

    id: str
    statement: str
    assumption_type: AssumptionType
    is_explicit: bool
    stated_by: str | None = None
    """Role or body the document attributes the assumption to. A role, not a person."""
    quantified_money: Money | None = None
    quantified_value: Quantity | None = None
    sensitivity_note: str | None = None
    applies_to_provision_ids: list[str] = Field(default_factory=list)
    span: Span


class Citation(AlephModel):
    """A reference from a document to something outside it.

    Captured so primary-source coverage can be measured against what the
    document itself relies on, rather than against an arbitrary reading list.
    """

    id: str
    cited_text: str
    target_kind: CitationTargetKind
    target_identifier: str | None = None
    target_title: str | None = None
    url: str | None = None
    provision_id: str | None = None
    span: Span


class Amendment(AlephModel):
    """A textual change a document makes to another instrument.

    ``before_text``/``after_text`` are kept verbatim so the substantive effect
    can be shown rather than characterised.
    """

    id: str
    operation: AmendmentOperation
    target_identifier: str | None = None
    target_title: str | None = None
    target_locator: str | None = None
    before_text: str | None = None
    after_text: str | None = None
    provision_id: str | None = None
    span: Span


class LegalDependency(AlephModel):
    """Something outside a document that its operation depends on.

    Unmet dependencies are the most common reason a provision that exists has no
    effect, and any impact statement that ignores them overstates the document.
    ``status`` is ``unknown`` when the document is silent: Aleph does not infer
    satisfaction.
    """

    id: str
    dependency_kind: DependencyKind
    identifier: str | None = None
    title: str | None = None
    status: DependencyStatus | None = None
    note: str | None = None
    provision_ids: list[str] = Field(default_factory=list)
    span: Span | None = None


class AffectedInstitution(AlephModel):
    """A body a document gives a role to.

    Kept distinct from populations and industries because institutions bear
    duties, while populations and industries bear effects.
    """

    id: str
    name: str
    role_in_document: InstitutionRole
    provision_ids: list[str] = Field(default_factory=list)
    span: Span | None = None


class AffectedPopulation(AlephModel):
    """A group a document names or defines as affected.

    Described by the document's own eligibility criteria rather than by an
    external demographic label, so Aleph never invents a constituency the text
    did not create. ``estimated_size`` is populated only when the DOCUMENT states
    it.
    """

    id: str
    label: str
    definition_criteria: str | None = None
    estimated_size: Quantity | None = None
    provision_ids: list[str] = Field(default_factory=list)
    span: Span | None = None


class AffectedIndustry(AlephModel):
    """An economic sector or activity a document names as affected."""

    id: str
    label: str
    classification_code: str | None = None
    classification_system: str | None = None
    """Left open: Aleph assumes no particular classification system."""
    provision_ids: list[str] = Field(default_factory=list)
    span: Span | None = None


class ExtractionWarning(AlephModel):
    """A recorded limitation of one reading of a document.

    Surfaced to the reader rather than hidden: knowing that numbering was guessed
    or that three pages were unreadable is part of knowing how much the analysis
    is worth.
    """

    code: ExtractionWarningCode
    severity: WarningSeverity
    message: str
    page: Annotated[int, Field(ge=1)] | None = None
    affected_field: str | None = None
    """Dotted path of the field whose reliability is reduced."""
    span: Span | None = None


class DocumentModel(AlephModel):
    """The structured reading of one source document (warm phase 1).

    Everything Aleph later asserts is anchored here. The model is shaped around
    three obligations: traceability (every item carries a verbatim span),
    separation of the document from the world (this records only what the
    document SAYS, never whether it is right), and document-agnosticism
    (identity, jurisdiction and type are open parameters, not a fixed list).
    Assumptions sit alongside provisions because a forecast in a document is only
    evaluable against the assumptions the document itself states.
    """

    schema_version: SchemaVersion | None = None
    data_status: DataStatus | None = None
    id: DocumentId
    identity: DocumentIdentity
    source: DocumentSource
    structure: DocumentStructure
    provisions: list[Provision] = Field(default_factory=list)
    definitions: list[Definition] = Field(default_factory=list)
    monetary_values: list[MonetaryValue] = Field(default_factory=list)
    quantities: list[QuantityMention] = Field(default_factory=list)
    deadlines: list[Deadline] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    amendments: list[Amendment] = Field(default_factory=list)
    legal_dependencies: list[LegalDependency] = Field(default_factory=list)
    affected_institutions: list[AffectedInstitution] = Field(default_factory=list)
    affected_populations: list[AffectedPopulation] = Field(default_factory=list)
    affected_industries: list[AffectedIndustry] = Field(default_factory=list)
    extraction_warnings: list[ExtractionWarning] = Field(default_factory=list)
    notes: str | None = None


# ---------------------------------------------------------------------------
# proposition.json  (warm phase 2: proposition_extraction)
# ---------------------------------------------------------------------------


class GroundedProvenance(Provenance):
    """Provenance that MUST carry a span, and therefore a quotable passage.

    The enforcement point for Aleph's traceability rule: extraction that cannot
    point at text is discarded, not downgraded to low confidence.
    """

    span: Span


class Negation(AlephModel):
    """Explicit record of whether a proposition asserts or denies.

    Structured rather than left in the text because negation is the single most
    fragile thing in paraphrase, and a dropped 'not' inverts a verdict.
    """

    is_negated: bool
    negated_element: str | None = None
    """What exactly is denied — the predicate, a quantity, an exception — since
    the scope of negation changes meaning."""
    cue_text: str | None = None


class PropositionScope(AlephModel):
    """The qualifiers that bound where, when, to whom and under what conditions.

    Kept apart from the text so a later check can ask "is this true within its
    stated scope?" instead of the unanswerable "is this true?". Empty fields
    mean the document stated no limit, NOT that the proposition is universal.
    """

    temporal: str | None = None
    geographic: str | None = None
    population: str | None = None
    conditions: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)


class Proposition(AlephModel):
    """One atomic, self-contained statement made by a document.

    Decomposition to this level is the point: a compound sentence like "the levy
    rises and small firms are exempt" can be half true, and a system that checks
    it as a unit reports a single misleading verdict. ``is_atomic`` false flags a
    proposition that still bundles two claims and must not be sent to
    single-verdict evaluation.
    """

    id: PropositionId
    text: Annotated[str, Field(min_length=1)]
    proposition_type: PropositionType
    statement_type: StatementType | None = None
    subject: str | None = None
    predicate_summary: str | None = None
    object: str | None = None
    quantities: list[Quantity] = Field(default_factory=list)
    money: list[Money] = Field(default_factory=list)
    provenance: GroundedProvenance
    """REQUIRED, with a verbatim passage. A proposition with no quotable passage
    is invalid, not merely weak."""
    derived_from_provision_id: ProvisionId | None = None
    derived_from_section_id: str | None = None
    confidence: Confidence | None = None
    """Confidence in the extraction — that the document says this, atomically and
    in this scope. NOT confidence that the proposition is true of the world."""
    negation: Negation | None = None
    scope: PropositionScope | None = None
    modality: Modality | None = None
    """'shall' vs 'may' vs 'is expected to' is the difference between a duty, a
    discretion and a projection."""
    hedges: list[str] = Field(default_factory=list)
    is_atomic: bool = True
    is_self_contained: bool = True
    related_proposition_ids: list[PropositionId] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class PropositionCoverage(AlephModel):
    """How much of a document the extraction actually reached.

    Published so silence about a section is visible as a gap rather than read as
    an absence of content.
    """

    provisions_total: Annotated[int, Field(ge=0)] | None = None
    provisions_with_propositions: Annotated[int, Field(ge=0)] | None = None
    sections_not_processed: list[str] = Field(default_factory=list)
    note: str | None = None


class PropositionSet(AlephModel):
    """The propositions extracted from one document (warm phase 2)."""

    schema_version: SchemaVersion | None = None
    data_status: DataStatus | None = None
    document_id: DocumentId
    generated_at: Timestamp | None = None
    extractor: str | None = None
    """Identifier and version of the component that produced this set, so a
    change of extractor invalidates rather than silently alters the record."""
    propositions: list[Proposition] = Field(default_factory=list)
    coverage: PropositionCoverage | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# topic_graph.json  (warm phase 3: topic_graph)
# ---------------------------------------------------------------------------


class NodeAttribute(AlephModel):
    """One typed key/value fact about a node.

    A list of pairs rather than a free-form map so that every field in an Aleph
    payload remains declared and closed.
    """

    key: str
    value: str
    source_ref: str | None = None


class ExternalIdentifier(AlephModel):
    """An identifier for a node in an outside register.

    Enables joining to external data without hard-coding any particular register.
    """

    scheme: str
    value: str


class GraphNode(AlephModel):
    """One entity a document touches.

    ``kind == person_role`` is deliberately a ROLE and never a named individual:
    the factual path must be structurally unable to see personal identity, and a
    graph node holding a person's name would defeat that.
    """

    id: NodeId
    kind: NodeKind
    label: str
    aliases: list[str] = Field(default_factory=list)
    """Other surface forms. Feeds retrieval: coverage of an entity is routinely
    published under a name the document never uses."""
    description: str | None = None
    salience: UnitInterval | None = None
    """How central the entity is to the document. A ranking aid for the UI, not a
    judgement of importance in the world."""
    provision_ids: list[ProvisionId] = Field(default_factory=list)
    proposition_ids: list[PropositionId] = Field(default_factory=list)
    evidence_refs: list[AlephId] = Field(default_factory=list)
    mentions: list[Span] = Field(default_factory=list)
    attributes: list[NodeAttribute] = Field(default_factory=list)
    external_ids: list[ExternalIdentifier] = Field(default_factory=list)
    confidence: Confidence | None = None


class GraphEdge(AlephModel):
    """One asserted relation between two nodes.

    An edge is a claim in miniature and is held to the same standard: it names
    its evidence, says whether the document made it or Aleph inferred it, and
    reports effect size only as coarsely as the evidence permits. ``basis`` must
    be surfaced by any interface — presenting an inferred edge as something the
    document said misattributes Aleph's reasoning to the source.
    """

    id: EdgeId
    kind: EdgeKind
    source: NodeId
    target: NodeId
    label: str | None = None
    basis: EdgeBasis | None = None
    direction: Direction | None = None
    magnitude: Magnitude | None = None
    """Coarse on purpose: a numeric edge weight would assert a precision the
    underlying text does not support."""
    time_horizon: TimeHorizon | None = None
    causality: Causality | None = None
    mechanism: str | None = None
    """Should be filled whenever ``direction`` is set: without a mechanism an
    effect edge is unfalsifiable."""
    quantity: Quantity | None = None
    money: Money | None = None
    conditions: list[str] = Field(default_factory=list)
    evidence_refs: list[AlephId] = Field(default_factory=list)
    """An empty list is permitted only with basis ``inferred``, and consumers
    should render such an edge as provisional."""
    provenance: Provenance | None = None
    confidence: Confidence | None = None
    note: str | None = None


class GraphStats(AlephModel):
    """Summary counts, so a UI can describe coverage without walking every edge.

    ``inferred_edge_count`` is the one to read first: a graph that is mostly
    inferred is a hypothesis and should be labelled as one.
    """

    node_count: Annotated[int, Field(ge=0)] | None = None
    edge_count: Annotated[int, Field(ge=0)] | None = None
    inferred_edge_count: Annotated[int, Field(ge=0)] | None = None
    unsupported_edge_count: Annotated[int, Field(ge=0)] | None = None
    isolated_node_count: Annotated[int, Field(ge=0)] | None = None


class TopicGraph(AlephModel):
    """Entities a document touches and the relations it asserts (warm phase 3).

    The graph exists to make the middle of an argument inspectable. "This measure
    helps small firms" hides three separate steps — which provision, through what
    mechanism, on which group — and once hidden none of them can be checked.
    There is no left-right axis anywhere in this object.
    """

    schema_version: SchemaVersion | None = None
    data_status: DataStatus | None = None
    document_id: DocumentId
    generated_at: Timestamp | None = None
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    stats: GraphStats | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# search_vocabulary.json  (warm phase 4: search_vocabulary)
# ---------------------------------------------------------------------------


class GeneratedQuery(AlephModel):
    """One concrete query aimed at a specific kind of source.

    Queries are typed by target because the same subject needs different phrasing
    in a statute register, a statistics portal and a news archive. A single
    generic query silently over-collects journalism and under-collects primary
    documents, which then distorts every downstream diversity and independence
    measure. Query generation is directed at SOURCE TYPES, never at positions.
    """

    id: str | None = None
    query_text: Annotated[str, Field(min_length=1)]
    target_source_type: TargetSourceType
    target_source_ids: list[SourceEntryId] = Field(default_factory=list)
    expected_evidence_tier: EvidenceTier | None = None
    language: str
    syntax: QuerySyntax | None = None
    date_from: DateStr | None = None
    date_to: DateStr | None = None
    additional_terms: list[str] = Field(default_factory=list)
    priority: Annotated[int, Field(ge=1, le=10)] | None = None
    """Execution order hint, 1 highest. Reflects expected retrieval value only."""
    rationale: str | None = None


class VocabularyTerm(AlephModel):
    """One retrieval term, with its derivation recorded.

    Provenance of a term matters: a phrase lifted from a heading is evidence
    about the document, while a model-expanded synonym is a guess, and a
    retrieval set built mostly from guesses should be treated as weaker.
    """

    id: str | None = None
    text: Annotated[str, Field(min_length=1)]
    language: str
    weight: UnitInterval
    """Expected retrieval value. A search-utility weight carrying no evaluative
    meaning about the subject."""
    source: TermSource
    normalized_form: str | None = None
    must_quote: bool = False
    ambiguity_note: str | None = None
    derived_from: str | None = None
    span: Span | None = None
    generated_queries: list[GeneratedQuery] = Field(default_factory=list)


class TermSets(AlephModel):
    """The vocabulary grouped by kind of name — all ten keys always present.

    An empty set is a reportable gap in retrieval coverage; an absent key would
    hide it. ``common_names`` in particular is usually the highest-recall group
    and is rarely present in the document itself, so an empty one is a warning
    that the search will systematically under-collect.
    """

    official_names: list[VocabularyTerm] = Field(default_factory=list)
    common_names: list[VocabularyTerm] = Field(default_factory=list)
    identifiers: list[VocabularyTerm] = Field(default_factory=list)
    abbreviations: list[VocabularyTerm] = Field(default_factory=list)
    political_terminology: list[VocabularyTerm] = Field(default_factory=list)
    """The contested vocabulary in circulation. Collected so Aleph can FIND all
    sides of a debate, including framings it does not adopt. Presence implies no
    endorsement, and these terms must never weight or filter a factual verdict."""
    technical_terminology: list[VocabularyTerm] = Field(default_factory=list)
    sector_terminology: list[VocabularyTerm] = Field(default_factory=list)
    synonyms: list[VocabularyTerm] = Field(default_factory=list)
    provision_names: list[VocabularyTerm] = Field(default_factory=list)
    actor_terms: list[VocabularyTerm] = Field(default_factory=list)
    """Institutions, bodies and ROLES. Personal names here would leak identity
    into retrieval and then into ranking."""


class SearchVocabulary(AlephModel):
    """The retrieval vocabulary generated from a document (warm phase 4).

    It exists because searching for a document's official title finds almost
    nothing: instruments are debated under nicknames, referred to by number, and
    covered in registers the source text never uses. A pipeline that searches
    only the PDF title under-collects systematically and then reports the
    resulting silence as an absence of coverage.
    """

    schema_version: SchemaVersion | None = None
    data_status: DataStatus | None = None
    document_id: DocumentId
    generated_at: Timestamp | None = None
    primary_language: str
    target_languages: list[str] = Field(default_factory=list)
    term_sets: TermSets
    expansion_notes: str | None = None
    known_gaps: list[str] = Field(default_factory=list)
    """Term categories the generator could not populate. Read by readiness
    scoring: an unpopulated category is a retrieval risk."""


# ---------------------------------------------------------------------------
# evidence.json  (warm phase 5: evidence_collection)
# ---------------------------------------------------------------------------


class EvidentialRelevance(AlephModel):
    """How much one item bears on ONE specific question.

    This object exists to stop the commonest failure in automated fact-checking:
    treating an authoritative-looking source as if it settled whatever question
    happens to be nearby. Relevance is a property of the (item, question) pair
    and is deliberately independent of the publisher's standing.

    ``can_establish`` and ``cannot_establish`` are both required and non-empty.
    An item whose ``cannot_establish`` list is empty has almost certainly not
    been thought about.
    """

    question: Annotated[str, Field(min_length=1)]
    relevance: UnitInterval
    can_establish: list[str] = Field(min_length=1)
    cannot_establish: list[str] = Field(min_length=1)
    why: str | None = None
    """Justification referring to the item's method and scope, never to who
    published it."""


class EvidenceItem(AlephModel):
    """One retrieved artefact, or one passage within it, and what it establishes.

    ``statement`` is the heart of the item: it says what this evidence shows, not
    what the retrieving query hoped it would show. Write "the agency's May
    projection is X" rather than "the cost is X".
    """

    id: AlephId
    source_ref: SourceRef
    tier: EvidenceTier
    """Repeated at item level so an item can be filtered without dereferencing
    its source. Tier constrains what an item can establish; it is never a ranking
    of trustworthiness."""
    statement: Annotated[str, Field(min_length=1)]
    spans: list[Span] = Field(min_length=1)
    """An evidence item with no quotable passage is not auditable and must not
    be used to move a verdict."""
    retrieved_at: Timestamp
    supports: list[AlephId] = Field(default_factory=list)
    contradicts: list[AlephId] = Field(default_factory=list)
    evidential_relevance: EvidentialRelevance
    strength: EvidenceStrength | None = None
    independence: Independence | None = None
    derived_from_evidence_id: AlephId | None = None
    """Set when this item restates another, so corroboration cannot double-count."""
    quantities: list[Quantity] = Field(default_factory=list)
    money: list[Money] = Field(default_factory=list)
    confidence: Confidence | None = None
    uncertainties: list[Uncertainty] = Field(default_factory=list)
    extraction_method: str | None = None
    notes: str | None = None


class EvidenceSet(AlephModel):
    """The evidence assembled for one question, with an honest account of its limits.

    ``independent_source_count`` is deliberately separate from the member count:
    ten copies of one wire report are ten members and one independent source, and
    only the latter may raise confidence.
    """

    id: AlephId
    question: Annotated[str, Field(min_length=1)]
    evidence_ids: list[AlephId] = Field(default_factory=list)
    """In the order Aleph considered them. Order must not affect a verdict; the
    neutrality report tests exactly that."""
    strength: EvidenceStrength
    independent_source_count: Annotated[int, Field(ge=0)]
    gaps: list[str] = Field(default_factory=list)
    summary: str
    confidence: Confidence | None = None


class RetrievalGap(AlephModel):
    """A search that returned nothing usable.

    Publishing failures of retrieval is how a reader tells a thin evidence base
    from a thorough one. A missing source is a reason to lower confidence, not a
    reason to stay silent.
    """

    question: Annotated[str, Field(min_length=1)]
    queries_tried: list[str] = Field(default_factory=list)
    expected_source_kind: EvidenceTier | None = None
    note: str


class EvidencePool(AlephModel):
    """The pool of evidence collected before any claim was evaluated.

    The organising principle: SOURCE AUTHORITY AND EVIDENTIAL RELEVANCE ARE
    DIFFERENT PROPERTIES. Presence in this pool is not endorsement — an item may
    be recorded precisely because it is weak, contradicted or off-point, and that
    judgement is carried in each item's :class:`EvidentialRelevance`.
    """

    schema_version: SchemaVersion
    data_status: DataStatus
    generated_at: Timestamp
    document_id: AlephId | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    evidence_sets: list[EvidenceSet] = Field(default_factory=list)
    retrieval_gaps: list[RetrievalGap] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# claim.json
# ---------------------------------------------------------------------------


class EpistemicCheckResult(AlephModel):
    """The outcome of one epistemic check on one claim.

    ``na`` is a first-class result: applying a causal-support test to a
    definitional statement would manufacture a failure. ``note`` is a required
    key so that a fail is never a bare label.
    """

    check: EpistemicCheck
    result: CheckOutcome
    note: str | None
    """Required key, nullable value. A result without a reason is not inspectable."""
    evidence_refs: list[AlephId] = Field(default_factory=list)


class RedactedContext(AlephModel):
    """The audit record of exactly what the blind evaluator was shown.

    Recorded so blindness can be *checked* after the fact rather than merely
    asserted. A reviewer who suspects a verdict was influenced by who spoke can
    read this object and see that the speaker was not in the input.

    ``withheld`` is required and non-empty: a blind evaluation that withheld
    nothing is not blind.
    """

    claim_text: Annotated[str, Field(min_length=1)]
    """The claim as presented, with speaker-identifying tokens already replaced
    by neutral placeholders such as 'the speaker'."""
    context_excerpts: list[str] = Field(default_factory=list)
    evidence_ids: list[AlephId] = Field(default_factory=list)
    """In the order presented. Order must not change the verdict; the
    ``evidence_order_shuffle`` perturbation tests that."""
    withheld: list[WithheldCategory] = Field(min_length=1)
    redaction_version: str
    """Version of the redaction component, so a change in what gets stripped is
    visible in the record."""


class BlindEvaluation(AlephModel):
    """Stage one: the only place a verdict may be written.

    SPEAKER, PARTY, COALITION, GOVERNMENT-OR-OPPOSITION STATUS AND OUTLET WERE
    WITHHELD AT THIS STAGE. This model has no property in which any of them could
    be recorded and ``extra='forbid'`` makes adding one impossible, so the
    verdict path is structurally incapable of seeing them. Any consumer wanting a
    verdict must read it from here: there is deliberately no verdict field at
    claim level that a later, attributed pass could overwrite.
    """

    evaluator_version: Annotated[str, Field(min_length=1)]
    redacted_context: RedactedContext
    verdict: Verdict
    reasoning: Annotated[str, Field(min_length=1)]
    """The chain from evidence to verdict, written so a reader can disagree with
    a specific step. Must refer to evidence, never to who made the claim."""
    evidence_refs: list[AlephId] = Field(default_factory=list)
    assumptions_required: list[str] = Field(default_factory=list)
    """A forecast judged ``forecast_conditional`` lists its conditions here
    rather than being graded true or false."""
    confidence: Confidence
    uncertainties: list[Uncertainty] = Field(default_factory=list)


class HistoricalConsistency(AlephModel):
    """Whether an actor's current claim sits with their earlier statements.

    Descriptive context for a reader, not a truth test: an actor who changed
    position may have changed it because the evidence changed. Inconsistency
    never alters a verdict.
    """

    assessment: HistoricalConsistencyAssessment
    prior_claim_refs: list[AlephId] = Field(default_factory=list)
    note: str | None = None


class RhetoricalObservation(AlephModel):
    """A named pattern in how a claim was expressed.

    Naming a rhetorical pattern is not a refutation: a claim delivered with
    urgency framing may still be true, and a claim delivered plainly may still be
    false. Recorded only after the verdict is fixed.
    """

    pattern: RhetoricalPattern
    span: Span | None = None
    note: str | None = None


class AttributedAnalysis(AlephModel):
    """Stage two: who said it and how, applied only after the blind verdict exists.

    Nothing here can change that verdict — there is no verdict, confidence,
    override or adjustment field, and the verdict lives in
    :class:`BlindEvaluation`, which this stage never rewrites. The purpose is
    context: a plainly-true claim can still be selectively framed, and a false
    claim is not made false by who made it.

    ``applied_after_verdict`` is pinned to ``True``; a record in which
    attribution preceded evaluation cannot be constructed.
    """

    applied_after_verdict: bool = True
    speaker_role: str | None = None
    """A generic functional role, never a private individual's name."""
    speaker_id: AlephId | None = None
    outlet_id: AlephId | None = None
    """Recorded for provenance. Outlet prestige carries no evidential weight
    anywhere in Aleph."""
    framing_notes: list[str] = Field(default_factory=list)
    historical_consistency: HistoricalConsistency | None = None
    rhetorical_pattern: list[RhetoricalObservation] = Field(default_factory=list)

    @field_validator("applied_after_verdict")
    @classmethod
    def _pinned_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError(
                "applied_after_verdict is pinned to true: the attributed stage runs "
                "only after the blind verdict has been recorded, and a record "
                "asserting otherwise would describe a pipeline Aleph does not have."
            )
        return value


class OmittedContext(AlephModel):
    """Material context a reader would need that a claim or article left out.

    Recorded separately from the verdict because a technically accurate statement
    can still mislead by omission — and because "this is missing" is an assertion
    Aleph must evidence like any other.
    """

    statement: Annotated[str, Field(min_length=1)]
    """Stated positively: what is true and was not said."""
    why_it_matters: Annotated[str, Field(min_length=1)]
    evidence_refs: list[AlephId] = Field(default_factory=list)
    materiality: Magnitude | None = None


class Claim(AlephModel):
    """A single assertion, as asserted, plus everything Aleph did with it.

    Note what is NOT here: no top-level verdict, no confidence and no score. The
    verdict exists only inside :attr:`blind_evaluation`, so there is no field an
    attributed pass could overwrite and no place for a speaker-influenced
    judgement to live.

    ``text`` is preserved unedited so a reader can check that Aleph did not
    evaluate a strawman; ``normalised_text`` is what the evaluator reasons about,
    and holding the two side by side is how paraphrase drift is caught.
    """

    id: AlephId
    text: Annotated[str, Field(min_length=1)]
    normalised_text: Annotated[str, Field(min_length=1)]
    statement_type: StatementType
    topic_refs: list[AlephId] = Field(default_factory=list)
    made_at: DateOrTimestamp | None
    """Required key. Load-bearing: a statement true when made and false later is
    not a lie, and the temporal_correctness check depends on this."""
    provenance: Provenance
    """Used for authenticity and attribution; withheld from the blind evaluator."""
    quantities: list[Quantity] = Field(default_factory=list)
    money: list[Money] = Field(default_factory=list)
    blind_evaluation: BlindEvaluation
    attributed_analysis: AttributedAnalysis | None
    """Required key, nullable value, so the two-stage design is explicit in every
    record rather than silently absent."""
    checks_applied: list[EpistemicCheckResult] = Field(min_length=1, max_length=10)
    """Checks that do not apply appear with result ``na`` rather than being
    omitted, so a reader can tell 'not applicable' from 'not tested'."""
    contradicts: list[AlephId] = Field(default_factory=list)
    cluster_id: AlephId | None = None
    omitted_context: list[OmittedContext] = Field(default_factory=list)
    article_id: AlephId | None = None
    proposition_refs: list[AlephId] = Field(default_factory=list)
    """The link back to the primary text."""

    @field_validator("checks_applied")
    @classmethod
    def _checks_are_unique(cls, value: list[EpistemicCheckResult]) -> list[EpistemicCheckResult]:
        seen: set[str] = set()
        for entry in value:
            key = json.dumps(entry.to_jsonable(), sort_keys=True)
            if key in seen:
                raise ValueError(
                    f"duplicate check result for {entry.check.value!r}: the ten "
                    "epistemic checks are a fixed list and repeating one would "
                    "misrepresent how many independent tests a verdict survived"
                )
            seen.add(key)
        return value


class ClaimSet(AlephModel):
    """Claims with their two-stage evaluations.

    Extraction is deliberately generous and evaluation deliberately strict: a
    claim may be recorded and then found ``unverifiable`` or
    ``not_a_factual_claim``, which is a real result and is shown as such rather
    than dropped.
    """

    schema_version: SchemaVersion
    data_status: DataStatus
    generated_at: Timestamp
    document_id: AlephId | None = None
    claims: list[Claim] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# The blindness boundary
# ---------------------------------------------------------------------------

#: What Aleph strips before any factual evaluation. Exported so the redaction
#: component and the audit record cannot drift apart.
DEFAULT_WITHHELD: Final[tuple[WithheldCategory, ...]] = (
    WithheldCategory.SPEAKER_NAME,
    WithheldCategory.SPEAKER_ROLE,
    WithheldCategory.PARTY,
    WithheldCategory.COALITION,
    WithheldCategory.GOVERNMENT_OR_OPPOSITION_STATUS,
    WithheldCategory.OUTLET,
    WithheldCategory.OUTLET_PRESTIGE,
    WithheldCategory.AUTHOR,
    WithheldCategory.PUBLICATION_VENUE,
    WithheldCategory.INSTITUTIONAL_AFFILIATION,
)

DEFAULT_REDACTION_VERSION: Final[str] = "aleph-redaction/1.0.0"


class RedactedClaimContext(AlephModel):
    """The ONLY input a blind factual evaluator may receive.

    This class is the mechanism behind Aleph's central promise. Speaker-blindness
    could have been a convention — "remember not to pass the speaker" — and
    conventions decay: someone adds a field for a good reason, someone else keys
    a heuristic off it, and a year later verdicts quietly depend on who is
    talking. So blindness is a *type* here instead.

    The class carries exactly four things: the claim text, the date it was made,
    the semantic context needed to interpret it, and the evidence. It has NO
    field for a speaker, a name, a role, a party, a coalition, a
    government-or-opposition status, an outlet, an author or an institutional
    affiliation. ``extra='forbid'`` means one cannot be supplied at construction,
    and ``frozen=True`` means one cannot be attached afterwards. To leak identity
    into the factual path, someone would have to edit this class — a change no
    reviewer could mistake for an accident.

    The date is kept because it is evidentially load-bearing and identity-free: a
    statement true when made and false later is not a false statement, and the
    ``temporal_correctness`` check cannot run without it.

    Construct via :meth:`from_claim`, which performs the structural strip.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        protected_namespaces=(),
        frozen=True,
        validate_default=True,
    )

    claim_text: Annotated[str, Field(min_length=1)]
    """The proposition to be evaluated, already scrubbed of attributive tokens."""

    made_at: DateOrTimestamp | None = None
    """When the claim was made. Identity-free and evidentially necessary."""

    context_excerpts: tuple[str, ...] = ()
    """Surrounding passages needed to interpret the claim — a definition, a
    comparison class, the sentence a pronoun refers to. Redacted of attribution
    like the claim itself."""

    evidence: tuple[EvidenceItem, ...] = ()
    """The evidence set, in presentation order. Order must not change the
    verdict, which the ``evidence_order_shuffle`` perturbation verifies."""

    withheld: tuple[WithheldCategory, ...] = DEFAULT_WITHHELD
    """What was removed. Carried so the audit record can state it; carrying the
    *categories* leaks nothing, since it names what is absent rather than what
    it was."""

    redaction_version: str = DEFAULT_REDACTION_VERSION

    @field_validator("withheld")
    @classmethod
    def _withheld_not_empty(
        cls, value: tuple[WithheldCategory, ...]
    ) -> tuple[WithheldCategory, ...]:
        if not value:
            raise ValueError(
                "withheld must name at least one category: an evaluation that "
                "withheld nothing is not a blind evaluation"
            )
        return value

    @classmethod
    def from_claim(
        cls,
        claim: Claim,
        evidence: Sequence[EvidenceItem] = (),
        *,
        claim_text: str | None = None,
        context_excerpts: Sequence[str] = (),
        withheld: Sequence[WithheldCategory] = DEFAULT_WITHHELD,
        redaction_version: str = DEFAULT_REDACTION_VERSION,
    ) -> RedactedClaimContext:
        """Strip identity from a claim and return what the evaluator may see.

        Everything identity-bearing on :class:`Claim` is dropped here and there
        is no parameter through which it could be reinstated:

        * ``provenance`` — carries ``source_id`` and the article it came from;
        * ``attributed_analysis`` — carries ``speaker_role``, ``speaker_id`` and
          ``outlet_id``, and is by design the stage that runs *after* this one;
        * ``article_id`` — identifies the outlet that carried the statement;
        * ``cluster_id``, ``topic_refs``, ``contradicts`` — cheap side channels,
          since knowing which cluster a claim sits in can imply who made it.

        What survives is the claim, when it was made, the context needed to read
        it, and the evidence — which is the complete set of things that bear on
        whether it is true.

        Args:
            claim: The claim to evaluate. Only identity-free parts are read.
            evidence: Evidence items to place before the evaluator, in order.
            claim_text: Text to evaluate. Defaults to ``claim.normalised_text``,
                the single checkable proposition with pronouns resolved. Pass an
                explicit value when a textual redactor has additionally scrubbed
                names *inside* the sentence — this class enforces the structural
                strip; scrubbing prose is the redactor's job and the two are kept
                separate so neither can be mistaken for the other.
            context_excerpts: Interpretive context, already redacted.
            withheld: Categories removed, for the audit record.
            redaction_version: Version of the redaction component.

        Returns:
            A frozen context object that has nowhere to put a speaker.
        """
        return cls(
            claim_text=claim_text if claim_text is not None else claim.normalised_text,
            made_at=claim.made_at,
            context_excerpts=tuple(context_excerpts),
            evidence=tuple(evidence),
            withheld=tuple(withheld),
            redaction_version=redaction_version,
        )

    def to_redacted_context(self) -> RedactedContext:
        """Render the auditable record of what the evaluator was shown.

        This is what goes into :attr:`BlindEvaluation.redacted_context`, so that
        blindness is an inspectable fact in the published bundle rather than a
        claim about the pipeline.
        """
        return RedactedContext(
            claim_text=self.claim_text,
            context_excerpts=list(self.context_excerpts),
            evidence_ids=[item.id for item in self.evidence],
            withheld=list(self.withheld),
            redaction_version=self.redaction_version,
        )


@runtime_checkable
class BlindEvaluator(Protocol):
    """The signature every factual evaluator must have.

    It takes a :class:`RedactedClaimContext` and nothing else. There is no
    ``claim`` parameter, no ``speaker`` parameter and no keyword arguments,
    because any of those would be a door through which identity could reach the
    verdict. An implementation that needs more than this context needs less
    ambition, not more input.
    """

    def __call__(self, context: RedactedClaimContext, /) -> BlindEvaluation:
        """Return a verdict derived from the redacted context alone."""
        ...


# ---------------------------------------------------------------------------
# news_article.json
# ---------------------------------------------------------------------------


class Publisher(AlephModel):
    """The outlet that published an item.

    Carries an identifier and a display name and deliberately no prestige, tier
    or credibility rating: outlet standing must never influence a factual verdict
    anywhere in Aleph.
    """

    id: AlephId
    name: Annotated[str, Field(min_length=1)]


class Quotation(AlephModel):
    """A quoted passage, attributed to a functional role rather than a person.

    Quotations are the raw material for claim extraction; keeping the verbatim
    text and its span means a reader can check that Aleph evaluated what was
    actually said. ``speaker_role`` is withheld from the blind evaluator when a
    claim is derived from this quotation.
    """

    text: Annotated[str, Field(min_length=1)]
    speaker_role: str | None
    """Required key, nullable value. A generic role, never a private
    individual's name in synthetic data."""
    span: Span
    claim_id: AlephId | None = None


class Prediction(AlephModel):
    """A forward-looking statement carried by an article.

    Tracked separately from claims because predictions cannot be true or false
    yet: they can only be conditional, falsifiable and eventually checkable.
    Recording the conditions and the date at which a prediction becomes evaluable
    is what stops Aleph from grading the future. ``falsifiable=False`` means the
    statement is rhetoric and must not be presented as a checkable forecast.
    """

    text: Annotated[str, Field(min_length=1)]
    speaker_role: str | None = None
    horizon: TimeHorizon
    conditions: list[str] = Field(default_factory=list)
    falsifiable: bool
    evaluable_after: DateStr | None = None
    claim_id: AlephId | None = None


class ImpactEmphasisEntry(AlephModel):
    """Which policy-effect axis an article foregrounds, and how strongly.

    A description of editorial attention, not an accusation: an article about
    municipal finance will legitimately emphasise the central-versus-local axis.
    Emphasis becomes informative only compared across coverage of the same
    document, where a systematic silence on one axis becomes visible.
    """

    axis: ImpactAxisKey
    emphasis: UnitInterval
    direction_emphasised: Direction | None = None
    note: str | None = None


class PrimarySourceGroundingEntry(AlephModel):
    """One instance of an article anchoring a statement in a primary source.

    The distinction between ``linked`` and ``named_without_link`` matters: an
    article that names a report without pointing at it asks the reader to take
    the outlet's word for what the report says, which is exactly the substitution
    of authority for evidence that Aleph refuses to make.
    """

    ref: AlephId
    kind: GroundingKind
    note: str | None = None


class NewsArticle(AlephModel):
    """One published item plus Aleph's extraction from it.

    An article is treated as an OBSERVATION ABOUT COVERAGE, not as evidence about
    the world: on its own it establishes that a given outlet published a given
    statement on a given date. Whether the statement is true is settled elsewhere,
    speaker-blind, using evidence ranked by relevance rather than by the standing
    of the outlet.

    ``body_available`` and ``paywalled`` are required and load-bearing: an
    analysis built from headlines alone is a weaker analysis, and the reader is
    entitled to know when that is what happened.
    """

    id: AlephId
    url: str | None
    """Required key. Null for synthetic items, which point at nothing because
    they describe nothing real."""
    headline: Annotated[str, Field(min_length=1)]
    """Verbatim: headline framing frequently diverges from the body, and that
    divergence is itself a finding."""
    dek: str | None = None
    publisher: Publisher
    author: str | None
    """Required key. A generic role string in synthetic data, never a real
    person's name; null when unbylined."""
    published_at: DateOrTimestamp | None
    retrieved_at: Timestamp
    language: str | None = None
    article_type: ArticleType
    word_count: Annotated[int, Field(ge=0)] | None = None
    neutral_summary: Annotated[str, Field(min_length=1)]
    """Every sentence checkable against the article itself. No evaluative
    adjectives, no characterisation of the outlet, no restatement of the
    article's framing as fact."""
    body_available: bool
    paywalled: bool
    claim_ids: list[AlephId] = Field(default_factory=list)
    quotations: list[Quotation] = Field(default_factory=list)
    predictions: list[Prediction] = Field(default_factory=list)
    framing_profile_id: FramingProfileId | None = None
    """Never collapse the referenced eight-dimension profile into a single bias
    number for display."""
    impact_emphasis: list[ImpactEmphasisEntry] = Field(default_factory=list)
    omitted_context: list[OmittedContext] = Field(default_factory=list)
    primary_source_grounding: list[PrimarySourceGroundingEntry] = Field(default_factory=list)
    independence: Independence
    derived_from_article_id: AlephId | None = None
    """Populating this is what makes the syndication collapse possible."""
    cluster_ids: list[AlephId] = Field(default_factory=list)
    confidence: Confidence | None = None
    """Confidence in the extraction from this article, not in the article's own
    assertions."""


class ArticleSet(AlephModel):
    """News and commentary items collected about a document."""

    schema_version: SchemaVersion
    data_status: DataStatus
    generated_at: Timestamp
    document_id: AlephId | None = None
    articles: list[NewsArticle] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# news_cluster.json  (warm phase 6: news_clustering)
# ---------------------------------------------------------------------------


class DateRange(AlephModel):
    """Span of publication dates covered by a cluster.

    A very short range with many members is a signature of syndication rather
    than of sustained independent attention.
    """

    start: DateStr
    end: DateStr


class SyndicationChain(AlephModel):
    """One traced path from an original item to the pieces that reproduce it.

    Chains are the mechanism by which apparent corroboration collapses back to
    its single source, so the evidence for the chain must be stated: a wrongly
    asserted chain would suppress genuine corroboration.
    """

    origin_article_id: AlephId
    downstream_article_ids: list[AlephId] = Field(min_length=1)
    """These contribute nothing to independent corroboration."""
    chain_kind: ChainKind
    evidence: Annotated[str, Field(min_length=1)]
    """Why Aleph believes these items share an origin: identical phrasing, an
    identical quotation set, a shared wire slug, publication within minutes of a
    press release."""
    confidence: Confidence | None = None


class SharedOriginSignal(AlephModel):
    """A concrete observation suggesting several items derive from one source.

    Kept separate from :class:`SyndicationChain` because a signal is a
    measurement while a chain is a conclusion, and a reader should be able to see
    the measurements that produced the conclusion.
    """

    kind: SharedOriginKind
    article_ids: list[AlephId] = Field(min_length=2)
    similarity: UnitInterval | None = None
    detail: Annotated[str, Field(min_length=1)]
    """The specific shared material, quoted where possible. A shared error is the
    strongest signal of all and should be quoted verbatim."""


class IndependenceAnalysis(AlephModel):
    """The count that matters.

    ``total_articles`` measures how loud the coverage was;
    ``distinct_original_sources`` measures how much was actually observed. Only
    ``independent_corroboration_count`` may be used to raise evidence confidence
    downstream. A cluster with fifty articles and one original source is fifty
    times louder and no better evidenced than a cluster with one article.
    """

    distinct_original_sources: Annotated[int, Field(ge=0)]
    total_articles: Annotated[int, Field(ge=0)]
    """A volume measure, never an evidence measure."""
    syndication_chains: list[SyndicationChain] = Field(default_factory=list)
    shared_origin_evidence: list[SharedOriginSignal] = Field(default_factory=list)
    independent_corroboration_count: Annotated[int, Field(ge=0)]
    """How many independent originals actually confirm the cluster's central
    factual content. This is the only number that may move confidence."""
    note: str | None = None


class NewsCluster(AlephModel):
    """A group of coverage or claims that belong together.

    REPEATED PUBLICATION IS NOT INDEPENDENT EVIDENCE. Forty articles carrying the
    same wire copy are one observation reproduced forty times, and treating volume
    as confirmation is the commonest way an automated pipeline manufactures false
    confidence. The label describes the subject matter and never characterises
    the outlets or their politics.
    """

    id: AlephId
    kind: ClusterKind
    label: Annotated[str, Field(min_length=1)]
    summary: str | None = None
    article_ids: list[AlephId] = Field(default_factory=list)
    claim_ids: list[AlephId] = Field(default_factory=list)
    date_range: DateRange
    independence_analysis: IndependenceAnalysis
    """Required. A cluster published without it would invite exactly the
    volume-as-truth reading Aleph exists to prevent."""
    topic_refs: list[AlephId] = Field(default_factory=list)
    confidence: Confidence | None = None
    uncertainties: list[Uncertainty] = Field(default_factory=list)


class NewsClusterSet(AlephModel):
    """Coverage grouped into clusters, each with an independence analysis."""

    schema_version: SchemaVersion
    data_status: DataStatus
    generated_at: Timestamp
    document_id: AlephId | None = None
    clusters: list[NewsCluster] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# framing_profile.json
# ---------------------------------------------------------------------------


class FramingDimension(AlephModel):
    """One 0-100 framing measurement, with everything needed to audit it.

    The score is meaningless without its components: each component names a
    specific passage or choice and how much it contributed. A framing score that
    cannot be opened and inspected is an accusation rather than a measurement,
    so a non-zero score with no components raises.

    Subclasses pin the polarity so no interface can mis-colour a dimension.
    """

    score: Score100
    polarity: Polarity
    components: list[Component] = Field(default_factory=list)
    evidence_refs: list[AlephId] = Field(default_factory=list)
    confidence: Confidence
    rationale: Annotated[str, Field(min_length=1)]
    """Justification a reader can argue with, referring to the article's text
    rather than to its outlet or presumed politics."""

    @model_validator(mode="after")
    def _score_is_inspectable(self) -> FramingDimension:
        _require_components(self.score, self.components, f"{type(self).__name__}")
        return self


class FramingDimensionLowerIsBetter(FramingDimension):
    """A dimension where a HIGH value indicates a problem in how an article is written."""

    polarity: Polarity = Polarity.LOWER_IS_BETTER

    @field_validator("polarity")
    @classmethod
    def _pinned(cls, value: Polarity) -> Polarity:
        if value is not Polarity.LOWER_IS_BETTER:
            raise ValueError(
                "polarity is pinned to lower_is_better for this dimension: a high "
                "score here is a finding against the article, never a merit"
            )
        return value


class FramingDimensionHigherIsBetter(FramingDimension):
    """A dimension where a HIGH value indicates better epistemic practice."""

    polarity: Polarity = Polarity.HIGHER_IS_BETTER

    @field_validator("polarity")
    @classmethod
    def _pinned(cls, value: Polarity) -> Polarity:
        if value is not Polarity.HIGHER_IS_BETTER:
            raise ValueError(
                "polarity is pinned to higher_is_better for this dimension: a high "
                "score here is a merit, never a finding against the article"
            )
        return value


class FramingDimensions(AlephModel):
    """Exactly the eight fixed framing dimensions. No more, no fewer, no aggregate.

    Fixing the set means two articles are always described along the same axes,
    and ``extra='forbid'`` means no ninth dimension — least of all a summary
    'bias' figure — can be added.
    """

    selection_asymmetry: FramingDimensionLowerIsBetter
    """How unevenly the article selects which facts, figures and voices to
    include — measured against what the primary document and available evidence
    contain, not against a notion of political balance."""
    loaded_language: FramingDimensionLowerIsBetter
    """Evaluative or emotionally charged wording where a neutral description was
    available. Components must quote the specific words."""
    context_omission: FramingDimensionLowerIsBetter
    certainty_inflation: FramingDimensionLowerIsBetter
    unsupported_causal_language: FramingDimensionLowerIsBetter
    """Scored on the strength of the causal warrant, never on whether the
    asserted cause is politically congenial."""
    opinion_as_fact: FramingDimensionLowerIsBetter
    """An opinion column is not penalised for containing opinion; it is measured
    on whether opinion is dressed as established fact."""
    source_diversity: FramingDimensionHigherIsBetter
    """Counts distinct originals: five quotations from one briefing are one
    source. Diversity of evidence, not of political affiliation."""
    primary_source_grounding: FramingDimensionHigherIsBetter

    def as_mapping(self) -> dict[FramingDimensionKey, FramingDimension]:
        """Return the eight dimensions keyed by :class:`FramingDimensionKey`."""
        return {FramingDimensionKey(name): getattr(self, name) for name in type(self).model_fields}


class FramingProfile(AlephModel):
    """An eight-dimension description of HOW an article presents its subject.

    Computed independently of WHAT it concludes. THESE EIGHT NUMBERS MUST NEVER
    BE COLLAPSED INTO A SINGLE 'BIAS' OR 'POLITICAL LEANING' SCORE, and no
    consumer may compute one: a scalar would hide the fact that heavy loaded
    language and excellent primary-source grounding are different properties
    pointing in different directions, and would inevitably be read as a
    left-right placement, which Aleph does not produce.

    A framing profile says nothing about whether the article's factual claims are
    true — that is decided separately and speaker-blind.
    """

    id: FramingProfileId
    article_id: AlephId
    """A profile is always about one published item. There is no outlet-level
    profile: scoring an outlet rather than a text would be exactly the
    reputation shortcut Aleph refuses."""
    profile_version: Annotated[str, Field(min_length=1)]
    generated_at: Timestamp | None = None
    dimensions: FramingDimensions
    overall_note: str | None = None
    """Must describe the pattern across dimensions rather than average them."""
    confidence: Confidence | None = None
    limitations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# impact_map.json
# ---------------------------------------------------------------------------


class ImpactAxis(AlephModel):
    """A single bipolar placement with everything needed to audit it.

    Negative means the ``negative_label`` pole. A score near zero may mean
    balanced effects OR offsetting effects OR no relevant provisions, which is
    why ``rationale`` and ``components`` are required and the score alone is
    never sufficient. This is a description of effects found in a text, not a
    political classification of anyone.
    """

    score: BipolarScore
    negative_label: Annotated[str, Field(min_length=1)]
    positive_label: Annotated[str, Field(min_length=1)]
    components: list[Component] = Field(min_length=1)
    """This array IS the finding; the score is only its summary. A score
    published without components is not an Aleph result."""
    evidence_refs: list[AlephId] = Field(default_factory=list)
    confidence: Confidence
    rationale: Annotated[str, Field(min_length=1)]
    """Written so a reader can dispute a specific component rather than the
    number as a whole."""

    @model_validator(mode="after")
    def _score_is_inspectable(self) -> ImpactAxis:
        _require_components(self.score, self.components, "ImpactAxis")
        return self


class ImpactAxes(AlephModel):
    """Exactly the seven fixed axes, always all present, never aggregated.

    ``extra='forbid'`` means no eighth axis and, critically, no summary
    'political position' field can be added here.
    """

    households_vs_firms: ImpactAxis
    redistribution_vs_growth: ImpactAxis
    public_vs_private_provision: ImpactAxis
    worker_protection_vs_flexibility: ImpactAxis
    environment_vs_project_acceleration: ImpactAxis
    central_vs_local: ImpactAxis
    current_relief_vs_long_term_investment: ImpactAxis

    def as_mapping(self) -> dict[ImpactAxisKey, ImpactAxis]:
        """Return the seven axes keyed by :class:`ImpactAxisKey`."""
        return {ImpactAxisKey(name): getattr(self, name) for name in type(self).model_fields}


class GroupImpact(AlephModel):
    """One group and how a document's provisions are estimated to reach it.

    ``evidence_quality`` is required and uses the same vocabulary as everywhere
    else: an ``insufficient`` entry is a legitimate, informative result and must
    be displayed as such rather than dropped for looking weak.
    ``direct_or_indirect`` matters because an effect running through three
    behavioural steps is a much softer finding than a statutory transfer.

    ``group`` is an open string: the canonical set is :class:`GroupKind`, but
    jurisdictions have groups Aleph cannot enumerate in advance.
    """

    group: Annotated[str, Field(min_length=1)]
    group_detail: str | None = None
    estimated_direction: Direction
    """``mixed`` and ``uncertain`` are first-class answers and must not be
    rounded to positive or negative for presentational tidiness."""
    magnitude: Magnitude
    evidence_quality: EvidenceStrength
    time_horizon: TimeHorizon
    direct_or_indirect: Causality
    supporting_evidence: list[AlephId] = Field(default_factory=list)
    rationale: Annotated[str, Field(min_length=1)]
    """The mechanism, stated concretely: which provision reaches this group and how."""
    uncertainties: list[Uncertainty] = Field(default_factory=list)
    money: list[Money] | None = None
    """Null or empty when no source quantifies it — never an invented figure."""
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def _unevidenced_entries_are_insufficient(self) -> GroupImpact:
        if (
            not self.supporting_evidence
            and self.evidence_quality is not EvidenceStrength.INSUFFICIENT
        ):
            raise ValueError(
                f"group impact for {self.group!r} lists no supporting evidence but "
                f"claims evidence_quality {self.evidence_quality.value!r}. An entry "
                "with no evidence must carry 'insufficient': saying who gains "
                "without saying how we know is the assertion Aleph exists to refuse."
            )
        return self


class ImpactMap(AlephModel):
    """Where a document's identified effects fall, and which groups they reach.

    THESE AXES DESCRIBE POLICY EFFECTS. THEY ARE NOT PARTY LABELS, not
    ideological placements, and must never be summed, averaged or projected onto
    a single left-right dimension — Aleph does not emit such a number and any
    consumer that manufactures one is misusing this model. A position on
    ``redistribution_vs_growth`` says which mechanisms the text contains, not who
    supports it: the same score is compatible with any political sponsorship.
    """

    schema_version: SchemaVersion
    data_status: DataStatus
    generated_at: Timestamp
    document_id: DocumentId
    map_version: Annotated[str, Field(min_length=1)] | None = None
    axes: ImpactAxes
    beneficiaries: list[GroupImpact] = Field(default_factory=list)
    cost_bearers: list[GroupImpact] = Field(default_factory=list)
    """The same group may appear in both lists with different provisions,
    horizons or magnitudes, and that is a finding rather than a contradiction."""
    method_note: str | None = None
    uncertainties: list[Uncertainty] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# contradiction.json
# ---------------------------------------------------------------------------


class ContradictionPosition(AlephModel):
    """One actor's stance on the question at issue.

    The verdict on the linked claim was produced without knowing the speaker;
    ``speaker_role`` appears here purely so a reader knows who is arguing, and it
    carries no evidential weight.
    """

    claim_id: AlephId
    speaker_role: str | None = None
    stance: Stance
    summary: Annotated[str, Field(min_length=1)]
    """The position in one sentence, in the actor's own terms but stripped of
    rhetoric, so positions can be compared on the same question."""
    evidence_cited_by_actor: list[AlephId] = Field(default_factory=list)
    """What someone cites is a fact about their argument, not a licence to judge
    them by a different standard."""


class SharedEvidenceItem(AlephModel):
    """One piece of evidence applied identically to every position in a cluster.

    Recording what it establishes AND what it cannot establish in the same object
    is what stops an authoritative-looking source from being read as settling
    more than it does — the standard trap in disputes about costings.
    """

    evidence_id: AlephId
    what_it_establishes: Annotated[str, Field(min_length=1)]
    what_it_cannot_establish: Annotated[str, Field(min_length=1)]
    """Required: the asymmetry between these two fields is usually where a
    dispute actually lives."""
    bears_on_positions: list[AlephId] = Field(default_factory=list)
    """Normally every position in the cluster. A shorter list must be explained
    in the conclusion's reasoning, because selective application is precisely
    what this model exists to prevent."""


class SourceStatement(AlephModel):
    """What a body of source material actually says about the question at issue.

    Held separately from the conclusion so a reader can check the raw material
    before reading Aleph's reading of it. For projections, ``assumptions`` are
    the whole story: two projections differing only in an assumed growth rate are
    not in factual conflict.
    """

    statement: Annotated[str, Field(min_length=1)]
    evidence_refs: list[AlephId] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class AlephConclusion(AlephModel):
    """What the shared evidence supports, stated plainly.

    Derived only from the evidence: the identity, standing, office or party of
    the actors is not an input, and a conclusion whose reasoning appeals to who
    said something is invalid. Where the evidence does not decide the question,
    the honest conclusion is ``unverifiable`` or ``forecast_conditional`` — a
    draw reported as a draw.
    """

    statement: Annotated[str, Field(min_length=1)]
    verdict: Verdict
    confidence: Confidence
    reasoning: Annotated[str, Field(min_length=1)]
    """Step by step, referring only to evidence and never to the standing of a
    speaker."""
    evidence_refs: list[AlephId] = Field(default_factory=list)


class ContradictionCluster(AlephModel):
    """One dispute, framed around a single proposition.

    Resolved by applying THE SAME EVIDENCE SET TO EVERY POSITION. That symmetry
    is the whole point: the ordinary failure mode of contradiction reporting is
    to describe a dispute as a clash of personalities, or to settle it by
    deferring to whichever speaker has more standing. A dispute that cannot be
    resolved on the available evidence is marked unresolvable and left open —
    manufacturing a winner would be worse than reporting a draw.

    If the positions cannot be expressed as stances on one question, they are not
    contradicting each other and the cluster should not exist.
    """

    id: AlephId
    question_at_issue: Annotated[str, Field(min_length=1)]
    """Getting this right is most of the work: a vague question lets two
    compatible statements look like a contradiction."""
    positions: list[ContradictionPosition] = Field(min_length=2)
    shared_evidence: list[SharedEvidenceItem] = Field(default_factory=list)
    what_the_primary_source_says: SourceStatement | None
    """Required key. Null when the primary source does not address the question —
    itself a common and important finding."""
    what_projections_say: SourceStatement | None
    """Required key. Kept separate from the primary source because a projection
    is evidence about an expectation, never about an outcome."""
    what_is_uncertain: list[Uncertainty] = Field(default_factory=list)
    aleph_conclusion: AlephConclusion
    resolvable: bool
    """False means the dispute turns on assumptions, values or facts not yet in
    existence, and no analysis of current sources will decide it."""
    resolvable_by: str | None = None
    topic_refs: list[AlephId] = Field(default_factory=list)
    cluster_id: AlephId | None = None


class ContradictionSet(AlephModel):
    """Places where two or more actors say incompatible things."""

    schema_version: SchemaVersion
    data_status: DataStatus
    generated_at: Timestamp
    document_id: AlephId | None = None
    clusters: list[ContradictionCluster] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# neutrality_report.json
# ---------------------------------------------------------------------------


class NeutralitySample(AlephModel):
    """The scope of a neutrality run.

    Flip rates are only meaningful against the number of runs that produced
    them, and ``claim_ids`` is published so the sample can be checked for skew —
    a sample containing only claims from one kind of speaker would undermine the
    whole exercise.
    """

    claims_tested: Annotated[int, Field(ge=0)]
    runs_total: Annotated[int, Field(ge=0)]
    claim_ids: list[AlephId] = Field(default_factory=list)
    selection_method: str | None = None
    """Exhaustive, random with a stated seed, or stratified. Convenience sampling
    must be declared."""


class ExampleDelta(AlephModel):
    """How much a single perturbed run differed from its original.

    A verdict that survives but whose confidence swings sharply is a softer
    version of the same defect and must be visible.
    """

    confidence_delta: Annotated[float, Field(ge=-1, le=1)]
    """Perturbed evidence_confidence minus original. Should be near zero:
    swapping a speaker is not new evidence."""
    framing_delta: Annotated[float, Field(ge=-100, le=100)] | None = None
    explanation_semantic_delta: UnitInterval
    """Reasoning rewritten around a new speaker while keeping the same verdict is
    still a leak."""
    verdict_changed: bool


class PerturbationExample(AlephModel):
    """One concrete before-and-after, kept so a reader can inspect a failure.

    Examples of non-flips are as worth keeping as flips.
    """

    claim_id: AlephId
    perturbation: PerturbationKind | None = None
    substitution: str | None = None
    """What was swapped, described without naming any real person or
    organisation."""
    original_verdict: Verdict
    perturbed_verdict: Verdict
    delta: ExampleDelta
    note: str | None = None


class PerturbationResult(AlephModel):
    """Outcome for one perturbation family.

    ``flips`` over ``runs`` is the headline. Zero runs means the family was not
    exercised and its zero flips prove nothing, which is why ``runs`` is required
    and must be read first. Every flip in a family is by construction
    unwarranted, because nothing evidentially relevant was altered.
    """

    runs: Annotated[int, Field(ge=0)]
    flips: Annotated[int, Field(ge=0)]
    flip_rate: UnitInterval | None = None
    """Omitted when ``runs`` is zero: a rate over no runs is not a low rate."""
    examples: list[PerturbationExample] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode="after")
    def _flips_within_runs(self) -> PerturbationResult:
        if self.flips > self.runs:
            raise ValueError(
                f"{self.flips} flips recorded over {self.runs} runs: a flip count "
                "above the run count means the harness lost track of what it tested"
            )
        return self


class Perturbations(AlephModel):
    """Exactly the six fixed perturbation families, always all present.

    Fixing the set prevents a favourable subset from being reported as the whole
    test.
    """

    speaker_swap: PerturbationResult
    """The claim is re-attributed to a different actor role. Any verdict change
    is a leak of speaker identity into the factual path."""
    source_swap: PerturbationResult
    party_swap: PerturbationResult
    """The most direct test of partisan asymmetry, and the only place in the
    entire system where party appears at all — as a variable being deliberately
    scrambled, never as an input to a verdict."""
    authority_removal: PerturbationResult
    """Verdicts that weaken when a source stops looking official were relying on
    authority rather than on relevance."""
    claim_paraphrase: PerturbationResult
    evidence_order_shuffle: PerturbationResult

    def as_mapping(self) -> dict[PerturbationKind, PerturbationResult]:
        """Return the six families keyed by :class:`PerturbationKind`."""
        return {PerturbationKind(name): getattr(self, name) for name in type(self).model_fields}


class NeutralityMetrics(AlephModel):
    """Cross-family aggregates.

    All four are properties of Aleph's OWN behaviour under substitution and none
    of them describes any document, outlet or political actor. The deltas are
    reported as magnitudes so offsetting swings cannot cancel out to a flattering
    zero.
    """

    verdict_flip_rate: UnitInterval
    """The headline defect measure. The target is zero and any non-zero value is
    a finding against Aleph."""
    confidence_delta: Annotated[float, Field(ge=0, le=1)]
    framing_delta: Annotated[float, Field(ge=0, le=100)]
    explanation_semantic_delta: UnitInterval
    """Catches the case where the verdict holds but the justification is quietly
    rebuilt around the substituted speaker."""


class NeutralityReport(AlephModel):
    """Results of re-running evaluations with irrelevant details substituted.

    THIS MEASURES INVARIANCE UNDER IRRELEVANT SUBSTITUTION. IT DOES NOT PROVE
    POLITICAL NEUTRALITY. A system can be perfectly invariant to swapping a
    speaker and still be wrong in a consistent direction, still select which
    claims to examine in a skewed way, and still inherit whatever slant its
    evidence corpus carries — none of which this test can see.

    ``interpretation_caveat`` is required, and must be displayed wherever
    ``neutrality_health`` is displayed, precisely so no consumer can show the
    score without the limits of what it means.
    """

    schema_version: SchemaVersion
    data_status: DataStatus
    generated_at: Timestamp
    report_version: Annotated[str, Field(min_length=1)]
    evaluator_version: Annotated[str, Field(min_length=1)]
    """A neutrality result belongs to a specific evaluator and is invalidated
    when that evaluator changes."""
    sample: NeutralitySample
    perturbations: Perturbations
    metrics: NeutralityMetrics
    neutrality_health: Score100
    """A measure of Aleph's own behaviour, not of any document, outlet or actor."""
    neutrality_health_polarity: Polarity = Polarity.HIGHER_IS_BETTER
    neutrality_health_components: list[Component] = Field(min_length=1)
    """An unexplained self-assessment score would be the least trustworthy number
    in the product."""
    confidence: Confidence
    interpretation_caveat: Annotated[str, Field(min_length=40)]
    limitations: list[str] = Field(default_factory=list)
    failures_to_investigate: list[PerturbationExample] = Field(default_factory=list)
    """One verdict that flips on an authority cue tells you more than a good
    average."""

    @field_validator("neutrality_health_polarity")
    @classmethod
    def _polarity_pinned(cls, value: Polarity) -> Polarity:
        if value is not Polarity.HIGHER_IS_BETTER:
            raise ValueError(
                "neutrality_health_polarity is pinned to higher_is_better so no "
                "interface can render a good neutrality result as a warning"
            )
        return value

    @model_validator(mode="after")
    def _health_is_inspectable(self) -> NeutralityReport:
        _require_components(
            self.neutrality_health, self.neutrality_health_components, "NeutralityReport"
        )
        return self


# ---------------------------------------------------------------------------
# readiness.json  (warm phase 7: readiness)
# ---------------------------------------------------------------------------


class ReadinessGap(AlephModel):
    """One specific, named hole in the evidence base.

    Written to be actionable: "no independent estimate of the cost figure" is a
    gap, "more research needed" is not. Naming the resolving evidence is what
    turns a low score into a task.
    """

    id: str | None = None
    dimension: ReadinessDimensionKey | None = None
    description: str
    severity: GapSeverity
    """``blocking`` means nothing may be published while it stands."""
    missing_kind: MissingKind
    what_would_resolve: str | None = None
    """Null only when nothing available could close it, which is itself a
    publishable finding."""
    affected_claim_ids: list[AlephId] = Field(default_factory=list)
    blocking_since: Timestamp | None = None


class ReadinessDimension(AlephModel):
    """One readiness dimension: a score, its components, its weight, its gaps.

    A dimension may never be reported as a bare number. ``weight`` is published
    so the aggregate can be recomputed and challenged. An empty ``components``
    array is valid only for a dimension scored zero for total absence of
    material.

    These measure Aleph's own evidence coverage — never the quality of the
    document and never the conduct of any actor.
    """

    score: Score100
    weight: Annotated[float, Field(ge=0, le=1)]
    rationale: str
    components: list[Component] = Field(default_factory=list)
    gaps: list[ReadinessGap] = Field(default_factory=list)
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def _score_is_inspectable(self) -> ReadinessDimension:
        _require_components(self.score, self.components, "ReadinessDimension")
        return self


class ReadinessDimensions(AlephModel):
    """The seven readiness dimensions, all required.

    Fixed keys rather than an open list: a dimension that could be omitted would
    be omitted precisely when it scored badly, and the absence would read as
    adequacy.
    """

    document_understanding: ReadinessDimension
    """Everything else rests on this, so a low score here caps the rest."""
    primary_source_coverage: ReadinessDimension
    """Reporting about a document is not the document."""
    news_coverage: ReadinessDimension
    """Deliberately not the leading dimension: abundant coverage of a subject is
    not evidence about it."""
    temporal_coverage: ReadinessDimension
    evidence_diversity: ReadinessDimension
    """Measures the shape of the evidence set, never the balance of opinions in it."""
    claim_coverage: ReadinessDimension
    source_independence: ReadinessDimension
    """Without this, syndication reads as corroboration and inflates every other
    number."""

    def as_mapping(self) -> dict[ReadinessDimensionKey, ReadinessDimension]:
        """Return the seven dimensions keyed by :class:`ReadinessDimensionKey`."""
        return {
            ReadinessDimensionKey(name): getattr(self, name) for name in type(self).model_fields
        }


class EvidenceInventory(AlephModel):
    """Raw counts behind the dimension scores.

    Published so a reader can sanity-check a percentage against the underlying
    totals instead of taking it on trust.
    """

    evidence_items: Annotated[int, Field(ge=0)] | None = None
    primary_documents: Annotated[int, Field(ge=0)] | None = None
    statistical_datasets: Annotated[int, Field(ge=0)] | None = None
    articles: Annotated[int, Field(ge=0)] | None = None
    clusters: Annotated[int, Field(ge=0)] | None = None
    independent_sources: Annotated[int, Field(ge=0)] | None = None
    """Distinct originating sources after syndicated and derivative items are
    collapsed."""
    distinct_tiers: Annotated[int, Field(ge=0)] | None = None
    claims_total: Annotated[int, Field(ge=0)] | None = None
    claims_with_evidence: Annotated[int, Field(ge=0)] | None = None
    propositions_total: Annotated[int, Field(ge=0)] | None = None
    earliest_evidence_date: DateStr | None = None
    latest_evidence_date: DateStr | None = None


class PhaseStatusEntry(AlephModel):
    """Outcome of one warm phase.

    A skipped phase with no note is an unexplained gap and should be treated as
    a failure.
    """

    phase: WarmPhase
    state: PhaseState
    completed_at: Timestamp | None = None
    item_count: Annotated[int, Field(ge=0)] | None = None
    note: str | None = None


class Readiness(AlephModel):
    """The gate between collecting context and publishing conclusions.

    Readiness answers one question: has Aleph gathered enough of the right kinds
    of material to say anything at all yet? The whole model exists to make a
    refusal possible and legible. A system that always produces an answer will,
    whenever the evidence is thin, produce a confident-sounding one — and the
    confidence will be the model's, not the evidence's.

    MODEL CONFIDENCE MUST NEVER STAND IN FOR MISSING EVIDENCE. A high
    ``model_confidence`` over an insufficient evidence base does not raise
    readiness, does not flip ``publishable``, and must never be displayed as
    reassurance. The only cure for a gap is retrieval.

    All dimensions are higher_is_better and measure the state of Aleph's evidence,
    never the merits of the document or of any actor.
    """

    schema_version: SchemaVersion | None = None
    data_status: DataStatus | None = None
    document_id: DocumentId
    generated_at: Timestamp | None = None
    overall_state: ReadinessState
    overall_score: Score100
    """A summary of the dimensions, never a substitute for reading them: a high
    average with one blocking gap is still blocked."""
    polarity: Polarity = Polarity.HIGHER_IS_BETTER
    dimensions: ReadinessDimensions
    blocking_gaps: list[ReadinessGap] = Field(default_factory=list)
    """At the top level, not buried in a dimension, because a single missing
    primary source can invalidate an otherwise well-covered analysis."""
    publishable: bool
    """Decided by evidence coverage alone. No level of model confidence may flip it."""
    why_not_publishable: str | None
    """Required key. Must be non-empty whenever ``publishable`` is false: a
    refusal without a stated reason is indistinguishable from a failure."""
    confidence: Confidence
    evidence_inventory: EvidenceInventory | None = None
    phase_status: list[PhaseStatusEntry] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    """The output of this object should be a work list, not a verdict on the
    document."""
    notes: str | None = None

    @field_validator("polarity")
    @classmethod
    def _polarity_pinned(cls, value: Polarity) -> Polarity:
        if value is not Polarity.HIGHER_IS_BETTER:
            raise ValueError(
                "readiness polarity is pinned to higher_is_better so a UI can never "
                "mis-colour a readiness score"
            )
        return value

    @model_validator(mode="after")
    def _refusal_is_explained(self) -> Readiness:
        if not self.publishable and not (self.why_not_publishable or "").strip():
            raise ValueError(
                "publishable is false but why_not_publishable is empty. Aleph is "
                "allowed to refuse; it is not allowed to refuse silently, because an "
                "unexplained refusal is indistinguishable from a crash."
            )
        return self


# ---------------------------------------------------------------------------
# source_registry.json
# ---------------------------------------------------------------------------


class Feed(AlephModel):
    """One machine-readable entry point for a source.

    Listed separately from ``base_url`` because polling a declared feed is both
    more complete and less intrusive than crawling a site, and because a source
    with no feed must be handled — and reported — differently.
    """

    url: str
    format: FeedFormat
    label: str | None = None
    language: str | None = None
    topic_hint: str | None = None
    """A hint for routing queries, not a filter on what may be collected."""
    auth_required: bool = False
    """Credentials themselves are NEVER stored in a registry file or any shipped
    artefact; they come from the environment at run time."""
    enabled: bool = True


class RobotsPolicy(AlephModel):
    """How Aleph must behave towards a host.

    Recorded per source so that compliance is a property of the data, not of
    whoever wrote the fetcher. ``crawl_allowed=None`` means not yet checked —
    which is not the same as permitted.
    """

    respect_robots: bool = True
    robots_url: str | None = None
    crawl_allowed: bool | None = None
    terms_url: str | None = None
    user_agent: str | None = None
    notes: str | None = None


class RateLimit(AlephModel):
    """Politeness budget for a source.

    Conservative defaults are preferred: a registry entry that gets Aleph blocked
    removes a source from every future analysis.
    """

    requests_per_minute: Annotated[float, Field(ge=0)] | None = None
    min_interval_seconds: Annotated[float, Field(ge=0)] | None = None
    max_concurrent: Annotated[int, Field(ge=1)] | None = None
    backoff_seconds: Annotated[float, Field(ge=0)] | None = None
    daily_request_cap: Annotated[int, Field(ge=0)] | None = None


class SourceRegistryEntry(AlephModel):
    """One retrievable source.

    Every field answers "what is this thing and how do we reach it", never "how
    much is it worth". There is NO credibility score, NO bias rating and NO
    political-leaning field, and ``extra='forbid'`` means one cannot be added by
    accident. That absence is the design: a numeric trust weight attached to an
    outlet would let institutional standing substitute for evidence, and would
    quietly turn every downstream verdict into a judgement about who was speaking.

    ``ownership_note`` is factual, public-record disclosure for a reader to weigh.
    Aleph never converts it into a score.
    """

    id: SourceEntryId
    name: str
    kind: SourceKind
    jurisdiction: Jurisdiction
    base_url: str
    feeds: list[Feed] = Field(default_factory=list)
    language: str
    additional_languages: list[str] = Field(default_factory=list)
    evidence_tier: EvidenceTier
    """What kind of artefact this source typically produces, which constrains
    what it can establish. NOT a ranking."""
    ownership_note: str | None = None
    """Null means unknown rather than independent."""
    typical_independence: Independence
    """Structural, not evaluative: it exists so ten outlets carrying one wire
    story are counted as one observation rather than ten corroborations."""
    robots_policy: RobotsPolicy | None = None
    rate_limit: RateLimit | None = None
    enabled: bool
    """Disabling is an operational decision (broken feed, blocked, out of scope)
    and must never be used to exclude a viewpoint."""
    topics: list[str] = Field(default_factory=list)
    paywall: Paywall | None = None
    added_at: DateStr | None = None
    last_verified_at: Timestamp | None = None
    notes: str | None = None
    """Operational notes only: feed quirks, encoding issues, granted permissions.
    Not commentary on the source's content or standing."""


class SourceRegistry(AlephModel):
    """The registry of sources Aleph may retrieve from.

    A description of what each source IS, deliberately not an assessment of how
    much any source should be believed. Fully jurisdiction-parameterised: adding
    a country means adding data, not code.
    """

    schema_version: SchemaVersion | None = None
    generated_at: Timestamp | None = None
    registry_version: str | None = None
    default_rate_limit: RateLimit | None = None
    sources: list[SourceRegistryEntry] = Field(default_factory=list)
    notes: str | None = None


# ---------------------------------------------------------------------------
# analysis_bundle.json
# ---------------------------------------------------------------------------


class ProvisionSummary(AlephModel):
    """One provision in the shape an interface needs.

    Denormalised from :class:`DocumentModel` so a UI can render and link
    provisions without walking the document tree. This is a projection, not a
    second source of truth: where it disagrees with ``document``, the document
    wins.
    """

    id: AlephId
    ref_label: str | None = None
    """The document's own label, exactly as printed. Null when the document does
    not number its provisions."""
    title: str | None = None
    summary: Annotated[str, Field(min_length=1)]
    """What the provision does, phrased so it could be checked against the quoted
    text. No evaluation of whether it is a good idea."""
    text: str | None = None
    """Verbatim. Null when only a summary was extractable, which weakens every
    downstream use of it."""
    spans: list[Span] = Field(default_factory=list)
    quantities: list[Quantity] = Field(default_factory=list)
    money: list[Money] = Field(default_factory=list)
    topic_refs: list[AlephId] = Field(default_factory=list)
    impact_axis_refs: list[ImpactAxisKey] = Field(default_factory=list)
    """The provision should appear as a named component inside each of those
    axes, which is how a reader gets from a dial back to a clause."""
    proposition_refs: list[AlephId] = Field(default_factory=list)
    status: str | None = None
    """Copied from the source, never inferred."""


class TimelineEvent(AlephModel):
    """One dated event in a document's life.

    Every entry carries ``evidence_refs`` because a timeline is a set of factual
    assertions like any other, and an unevidenced entry would smuggle a narrative
    into what looks like a neutral chronology. Events whose date is unknown are
    omitted rather than guessed.
    """

    date: DateStr
    label: Annotated[str, Field(min_length=1)]
    """Describes what happened rather than characterising it."""
    description: str | None = None
    kind: TimelineEventKind
    evidence_refs: list[AlephId] = Field(default_factory=list)
    """An entry with none must be treated as unverified by any consumer."""


class Methodology(AlephModel):
    """What produced a bundle and what it cannot do.

    ``limitations`` is required and non-empty: every analysis has limits, and a
    methodology block claiming none would itself be the strongest evidence that
    the analysis was not examined carefully.
    """

    pipeline_version: Annotated[str, Field(min_length=1)]
    model_provider: Annotated[str, Field(min_length=1)]
    """Including the deterministic mock provider when no live model was called.
    Named because every model carries its own dispositions and a reader is
    entitled to know which one judged these claims."""
    phases_completed: list[WarmPhase] = Field(default_factory=list)
    """A missing phase is not a formality: skipping search_vocabulary or
    evidence_collection means verdicts rest on whatever happened to be at hand."""
    limitations: list[str] = Field(min_length=1)
    generated_by: Annotated[str, Field(min_length=1)]

    @field_validator("phases_completed")
    @classmethod
    def _phases_unique(cls, value: list[WarmPhase]) -> list[WarmPhase]:
        if len(set(value)) != len(value):
            raise ValueError("phases_completed must not repeat a phase")
        return value


class AnalysisBundle(AlephModel):
    """The single export the frontend consumes: one document's complete analysis.

    Read it as a chain of custody rather than a report. The warm phases come
    first — the document as parsed, the propositions extracted from it, the topic
    graph, the vocabulary those topics generated, and the evidence that
    vocabulary retrieved — and only then the evaluated material: claims with
    their speaker-blind verdicts, the coverage that carried them, the clusters
    showing how much of that coverage was actually independent, and the
    contradictions resolved against shared evidence.

    ``readiness`` states whether the evidence base was ever thick enough to
    publish verdicts, and it may say no. A bundle whose readiness is
    ``insufficient`` is a valid and honest bundle, and consumers must render its
    verdicts with that caveat rather than suppress the caveat to look decisive.

    ``data_status`` must be shown to the reader: a bundle marked ``synthetic``
    describes no real statement by any real person or outlet, and any interface
    that hides that banner is misrepresenting the product.

    Nothing in this bundle is a left-right score, and none exists to be computed
    from it.
    """

    schema_version: SchemaVersion = SCHEMA_VERSION
    data_status: DataStatus
    generated_at: Timestamp
    """Evidence retrieved after this instant is not in the bundle, which matters
    for any claim about an ongoing process."""
    document: DocumentModel
    propositions: PropositionSet
    topic_graph: TopicGraph
    search_vocabulary: SearchVocabulary
    """Published because the vocabulary determines what evidence could possibly
    have been found — a reader auditing for selection effects should start here."""
    provisions: list[ProvisionSummary] = Field(default_factory=list)
    impact_map: ImpactMap
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    articles: list[NewsArticle] = Field(default_factory=list)
    clusters: list[NewsCluster] = Field(default_factory=list)
    contradictions: list[ContradictionCluster] = Field(default_factory=list)
    neutrality_report: NeutralityReport
    """Aleph's measurement of its own invariance. It does not prove political
    neutrality, and its interpretation_caveat must be displayed wherever its
    score is."""
    readiness: Readiness
    timeline: list[TimelineEvent] = Field(default_factory=list)
    methodology: Methodology
    """Required, and required to be reachable from every view of the analysis."""
    framing_profiles: list[FramingProfile] | None = None
    """Optional because framing analysis may not have run; never optional to
    display in full once present, since the eight dimensions must not be
    collapsed into one number."""
    source_registry: SourceRegistry | None = None


__all__ = [
    # contract constants
    "SCHEMA_VERSION",
    "SCHEMA_VERSION_PATTERN",
    "TIMESTAMP_PATTERN",
    "DATE_PATTERN",
    "DATE_OR_TIMESTAMP_PATTERN",
    "DEFAULT_WITHHELD",
    "DEFAULT_REDACTION_VERSION",
    # scalar aliases
    "SchemaVersion",
    "Timestamp",
    "DateStr",
    "DateOrTimestamp",
    "UnitInterval",
    "Score100",
    "BipolarScore",
    "AlephId",
    "DocumentId",
    "ProvisionId",
    "PropositionId",
    "NodeId",
    "EdgeId",
    "SourceEntryId",
    "FramingProfileId",
    "DocumentSlug",
    "NonEmptyStr",
    # base
    "AlephModel",
    # common.json
    "Money",
    "Quantity",
    "Span",
    "Provenance",
    "ConfidenceBasis",
    "Confidence",
    "Component",
    "SourceRef",
    "Uncertainty",
    # document.json
    "PageRange",
    "Jurisdiction",
    "DocumentIdentifier",
    "AuthorshipEntry",
    "DocumentDates",
    "DocumentIdentity",
    "ExtractionQuality",
    "DocumentSource",
    "Section",
    "DocumentStructure",
    "Provision",
    "Definition",
    "MonetaryValue",
    "QuantityMention",
    "Deadline",
    "Assumption",
    "Citation",
    "Amendment",
    "LegalDependency",
    "AffectedInstitution",
    "AffectedPopulation",
    "AffectedIndustry",
    "ExtractionWarning",
    "DocumentModel",
    # proposition.json
    "GroundedProvenance",
    "Negation",
    "PropositionScope",
    "Proposition",
    "PropositionCoverage",
    "PropositionSet",
    # topic_graph.json
    "NodeAttribute",
    "ExternalIdentifier",
    "GraphNode",
    "GraphEdge",
    "GraphStats",
    "TopicGraph",
    # search_vocabulary.json
    "GeneratedQuery",
    "VocabularyTerm",
    "TermSets",
    "SearchVocabulary",
    # evidence.json
    "EvidentialRelevance",
    "EvidenceItem",
    "EvidenceSet",
    "RetrievalGap",
    "EvidencePool",
    # claim.json
    "EpistemicCheckResult",
    "RedactedContext",
    "BlindEvaluation",
    "HistoricalConsistency",
    "RhetoricalObservation",
    "AttributedAnalysis",
    "OmittedContext",
    "Claim",
    "ClaimSet",
    "RedactedClaimContext",
    "BlindEvaluator",
    # news_article.json
    "Publisher",
    "Quotation",
    "Prediction",
    "ImpactEmphasisEntry",
    "PrimarySourceGroundingEntry",
    "NewsArticle",
    "ArticleSet",
    # news_cluster.json
    "DateRange",
    "SyndicationChain",
    "SharedOriginSignal",
    "IndependenceAnalysis",
    "NewsCluster",
    "NewsClusterSet",
    # framing_profile.json
    "FramingDimension",
    "FramingDimensionLowerIsBetter",
    "FramingDimensionHigherIsBetter",
    "FramingDimensions",
    "FramingProfile",
    # impact_map.json
    "ImpactAxis",
    "ImpactAxes",
    "GroupImpact",
    "ImpactMap",
    # contradiction.json
    "ContradictionPosition",
    "SharedEvidenceItem",
    "SourceStatement",
    "AlephConclusion",
    "ContradictionCluster",
    "ContradictionSet",
    # neutrality_report.json
    "NeutralitySample",
    "ExampleDelta",
    "PerturbationExample",
    "PerturbationResult",
    "Perturbations",
    "NeutralityMetrics",
    "NeutralityReport",
    # readiness.json
    "ReadinessGap",
    "ReadinessDimension",
    "ReadinessDimensions",
    "EvidenceInventory",
    "PhaseStatusEntry",
    "Readiness",
    # source_registry.json
    "Feed",
    "RobotsPolicy",
    "RateLimit",
    "SourceRegistryEntry",
    "SourceRegistry",
    # analysis_bundle.json
    "ProvisionSummary",
    "TimelineEvent",
    "Methodology",
    "AnalysisBundle",
]
