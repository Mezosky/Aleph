"""Ranking evidence for one question, without ever asking who published it.

Every automated fact-checking system has to decide which of the things it found
matter most. The usual answer is a source-authority weight: a table of outlets
and institutions with numbers beside them. It is an appealing answer because it
is easy and because it is usually *approximately right*, and it is nonetheless
the thing this module exists to refuse.

An authority weight fails in a specific, predictable way. It cannot distinguish
"this source is generally reliable" from "this source bears on this question".
A national statistics office is an excellent source and establishes nothing
whatever about what a bill's text says. A ministry's press office is the
definitive source for what the ministry claimed and no source at all for whether
the claim is true. An authority-weighted ranking gets both of those backwards and
reports the result with confidence, because the weight it used was never about
the question being asked.

So ranking here is a function of the **(artefact, question) pair**:

* **Tier–question affinity.** :data:`TIER_CAPABILITIES` states, for each of the
  nine evidence tiers, what that class of artefact *can* and *cannot* establish,
  and how strongly it bears on each kind of question. It is a published table, not
  a hidden constant — :func:`tier_capability_table` renders it for the interface
  so a reader can see why an item ranked where it did and disagree with the rule
  rather than with the outcome.
* **Topical relevance** to this question's actual terms.
* **Specificity**: does the item pin down a scope, a period, a defined quantity,
  or does it gesture.
* **Quantitative content**, counted only when the question is quantitative.
* **Recency**, weighted by how much the question's answer can change over time —
  which for "what does the text say" is not at all.
* **Independent corroboration** from other items in the same candidate set,
  discounted for anything that restates another item.

The prohibition is structural, not documentary. :class:`_ScoringView` is the only
thing the scorer sees, and it has no publisher, no outlet name, no institution and
no title; source identity survives only as an opaque token that can be compared
for equality when counting corroboration and used for nothing else. Ties break on
a content hash rather than on an item id, so not even alphabetical outlet order
can influence a position. And :func:`authority_invariance_check` runs the ranking
again with every publisher identity permuted and asserts the order is unchanged —
so the property is *tested at run time*, not asserted in a comment.

Two consequences are worth stating plainly, because they look like bugs and are
not. A political statement ranks near the bottom for a question about a measured
quantity and near the top for a question about what an actor committed to; that
is the same artefact correctly placed twice. And an item may score highly while
being false — relevance is about what an artefact class can bear on, and the
truth of a particular claim is settled by the speaker-blind evaluator, elsewhere,
using what this module hands it.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from aleph.core.enums import (
    ConfidenceEffect,
    ConfidenceFactor,
    Direction,
    EvidenceStrength,
    EvidenceTier,
    Independence,
)
from aleph.core.ids import stable_hash
from aleph.core.models import (
    Component,
    Confidence,
    ConfidenceBasis,
    EvidenceItem,
    EvidenceSet,
)

__all__ = [
    "DEFAULT_RANK_CONFIG",
    "TIER_CAPABILITIES",
    "AuthorityInvarianceReport",
    "EvidenceRanking",
    "QuestionKind",
    "RankConfig",
    "RankedEvidence",
    "TierCapability",
    "authority_invariance_check",
    "classify_question",
    "evidence_strength_for",
    "rank_evidence",
    "tier_capability_table",
    "to_evidence_set",
]


# ---------------------------------------------------------------------------
# Question kinds
# ---------------------------------------------------------------------------


class QuestionKind(StrEnum):
    """What sort of thing a question is asking for.

    The axis along which artefact classes differ. Two questions about the same
    subject — "what does the provision say about exemptions" and "did exemptions
    reduce collection" — need entirely different evidence, and a ranking that
    cannot tell them apart will hand back the same list twice and be wrong once.

    Deliberately not in :mod:`aleph.core.enums`: this is a distinction internal to
    ranking, not part of the published data contract, and adding it there would
    commit the frontend to a vocabulary it does not consume.
    """

    TEXTUAL_CONTENT = "textual_content"
    """What does a document actually say?"""
    FORMAL_PROCESS = "formal_process"
    """What was formally introduced, amended, decided or recorded, and when?"""
    MEASURED_QUANTITY = "measured_quantity"
    """What is or was the measured value of something?"""
    CAUSAL_EFFECT = "causal_effect"
    """Did one thing cause another?"""
    PROJECTION = "projection"
    """What is expected to happen, and under what assumptions?"""
    ATTRIBUTION = "attribution"
    """Who said or committed to what, and when?"""
    LEGAL_INTERPRETATION = "legal_interpretation"
    """What does a text mean, or require, as a matter of law?"""
    IMPLEMENTATION_STATUS = "implementation_status"
    """Was something actually done, by the deadline, as written?"""
    PUBLIC_REACTION = "public_reaction"
    """How did people, sectors or institutions respond?"""
    UNKNOWN = "unknown"
    """Unclassifiable. Treated as a flat prior across tiers rather than as an
    excuse to fall back on source standing — a question Aleph cannot type is a
    reason to be less confident, not a licence to guess by reputation."""


#: How fast a question's answer goes stale, in days. ``None`` means recency does
#: not bear on the question at all: a fifty-year-old statute says today exactly
#: what it said when it was enacted, and penalising an old primary document for
#: being old would systematically demote the best evidence there is.
QUESTION_RECENCY_HALF_LIFE: Final[Mapping[QuestionKind, float | None]] = {
    QuestionKind.TEXTUAL_CONTENT: None,
    QuestionKind.FORMAL_PROCESS: None,
    QuestionKind.LEGAL_INTERPRETATION: 1825.0,
    QuestionKind.MEASURED_QUANTITY: 365.0,
    QuestionKind.CAUSAL_EFFECT: 1825.0,
    QuestionKind.PROJECTION: 180.0,
    QuestionKind.ATTRIBUTION: None,
    QuestionKind.IMPLEMENTATION_STATUS: 90.0,
    QuestionKind.PUBLIC_REACTION: 120.0,
    QuestionKind.UNKNOWN: 730.0,
}

#: How much a question turns on numbers. Scales the quantitative-content
#: component, which is dropped entirely at zero rather than scored as an absence.
QUESTION_QUANTITATIVENESS: Final[Mapping[QuestionKind, float]] = {
    QuestionKind.TEXTUAL_CONTENT: 0.2,
    QuestionKind.FORMAL_PROCESS: 0.0,
    QuestionKind.LEGAL_INTERPRETATION: 0.0,
    QuestionKind.MEASURED_QUANTITY: 1.0,
    QuestionKind.CAUSAL_EFFECT: 0.7,
    QuestionKind.PROJECTION: 0.9,
    QuestionKind.ATTRIBUTION: 0.0,
    QuestionKind.IMPLEMENTATION_STATUS: 0.3,
    QuestionKind.PUBLIC_REACTION: 0.0,
    QuestionKind.UNKNOWN: 0.4,
}


# ---------------------------------------------------------------------------
# The tier capability matrix
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TierCapability:
    """What one class of artefact can and cannot settle.

    The heart of the module, and written as prose rather than as numbers alone
    because the numbers are only defensible if the sentences behind them are. A
    reader who thinks ``official_technical_report`` should bear more strongly on
    causal questions can read the ``cannot_establish`` list and argue with the
    reasoning; a reader given only a coefficient can only argue with the result.

    ``structurally_incapable`` is the strong form: question kinds this artefact
    class *cannot* answer at all, however good an instance of it is. An item in
    such a tier is not merely down-weighted for such a question, it is capped, and
    the cap is reported in the item's components so nobody mistakes a low position
    for a low-quality source.
    """

    tier: EvidenceTier
    summary: str
    can_establish: tuple[str, ...]
    cannot_establish: tuple[str, ...]
    affinity: Mapping[QuestionKind, float]
    structurally_incapable: frozenset[QuestionKind]

    def affinity_for(self, kind: QuestionKind) -> float:
        """Bearing of this artefact class on this kind of question, in [0,1]."""
        if kind is QuestionKind.UNKNOWN:
            # A flat prior. An unclassifiable question must not be answered by
            # falling back on which tier "sounds" most authoritative.
            return 0.5
        return self.affinity.get(kind, 0.4)


def _capability(
    tier: EvidenceTier,
    summary: str,
    can: Sequence[str],
    cannot: Sequence[str],
    affinity: Mapping[QuestionKind, float],
    incapable: Sequence[QuestionKind] = (),
) -> TierCapability:
    return TierCapability(
        tier=tier,
        summary=summary,
        can_establish=tuple(can),
        cannot_establish=tuple(cannot),
        affinity=dict(affinity),
        structurally_incapable=frozenset(incapable),
    )


K = QuestionKind

#: The published tier-capability matrix. Every ranking decision traces to a row
#: here, and :func:`tier_capability_table` renders it for the methodology page.
#:
#: Read the rows as claims about ARTEFACT CLASSES, never about institutions. The
#: same body produces artefacts in several tiers — a statistics agency publishes
#: datasets (``statistical_dataset``) and press notices (``political_statement``)
#: — and they establish quite different things. Nothing here says one tier is
#: better than another; the table says what each is *for*.
TIER_CAPABILITIES: Final[Mapping[EvidenceTier, TierCapability]] = {
    EvidenceTier.PRIMARY_DOCUMENT: _capability(
        EvidenceTier.PRIMARY_DOCUMENT,
        "The instrument itself. Definitive about its own text and about nothing else.",
        can=[
            "what the text says, verbatim, including its scope, conditions and exceptions",
            "the definitions the instrument adopts for its own purposes",
            "the projections and assumptions the issuing body committed to in writing",
            "the dates, deadlines and obligations the text sets",
        ],
        cannot=[
            "whether the projections it states will hold",
            "what effects it produced once in force",
            "whether it was implemented as written",
            "how anyone outside the issuing body interpreted or reacted to it",
        ],
        affinity={
            K.TEXTUAL_CONTENT: 1.0,
            K.FORMAL_PROCESS: 0.6,
            K.LEGAL_INTERPRETATION: 0.8,
            K.MEASURED_QUANTITY: 0.3,
            K.PROJECTION: 0.35,
            K.ATTRIBUTION: 0.5,
            K.CAUSAL_EFFECT: 0.1,
            K.IMPLEMENTATION_STATUS: 0.15,
            K.PUBLIC_REACTION: 0.05,
        },
        incapable=[K.CAUSAL_EFFECT, K.PUBLIC_REACTION],
    ),
    EvidenceTier.LEGISLATIVE_RECORD: _capability(
        EvidenceTier.LEGISLATIVE_RECORD,
        "The formal record of procedure. Definitive about what was done, not about whether "
        "it was right.",
        can=[
            "what was formally introduced, amended, withdrawn or voted, and when",
            "the procedural state of an instrument at a given date",
            "the institutional positions formally entered into the record",
            "which bodies and committees took which formal steps",
        ],
        cannot=[
            "whether a projection stated in the chamber is correct",
            "the real-world effect of anything decided",
            "what was agreed outside the recorded proceedings",
            "whether a recorded intention was ever carried out",
        ],
        affinity={
            K.TEXTUAL_CONTENT: 0.7,
            K.FORMAL_PROCESS: 1.0,
            K.LEGAL_INTERPRETATION: 0.6,
            K.MEASURED_QUANTITY: 0.2,
            K.PROJECTION: 0.2,
            K.ATTRIBUTION: 0.85,
            K.CAUSAL_EFFECT: 0.1,
            K.IMPLEMENTATION_STATUS: 0.35,
            K.PUBLIC_REACTION: 0.2,
        },
        incapable=[K.CAUSAL_EFFECT],
    ),
    EvidenceTier.OFFICIAL_TECHNICAL_REPORT: _capability(
        EvidenceTier.OFFICIAL_TECHNICAL_REPORT,
        "An official body's own analysis. Definitive about what that body assumed and "
        "estimated; not a verdict on whether the estimate is right.",
        can=[
            "the methodology, assumptions and scope the issuing body used",
            "the official estimate of record, and how it changed between versions",
            "which effects were modelled and which were explicitly excluded",
            "the data the body relied on and the period it covers",
        ],
        cannot=[
            "whether the estimate turns out to be correct",
            "effects the stated methodology did not model",
            "anything outside the report's declared scope, period or population",
            "that the assumptions are reasonable, as distinct from stated",
        ],
        affinity={
            K.TEXTUAL_CONTENT: 0.4,
            K.FORMAL_PROCESS: 0.4,
            K.LEGAL_INTERPRETATION: 0.3,
            K.MEASURED_QUANTITY: 0.75,
            K.PROJECTION: 0.8,
            K.ATTRIBUTION: 0.5,
            K.CAUSAL_EFFECT: 0.45,
            K.IMPLEMENTATION_STATUS: 0.6,
            K.PUBLIC_REACTION: 0.1,
        },
        incapable=[K.PUBLIC_REACTION],
    ),
    EvidenceTier.STATISTICAL_DATASET: _capability(
        EvidenceTier.STATISTICAL_DATASET,
        "A measurement. Definitive about the value under its own definitions, silent about "
        "why the value is what it is.",
        can=[
            "the measured value within the stated definition, method and reference period",
            "the direction and size of an observed change over comparable periods",
            "the coverage and known limitations of the measurement",
        ],
        cannot=[
            "why the value moved",
            "the effect of any particular policy on it",
            "values for populations, periods or definitions it does not cover",
            "anything about a concept it does not measure, however similarly named",
        ],
        affinity={
            K.TEXTUAL_CONTENT: 0.1,
            K.FORMAL_PROCESS: 0.1,
            K.LEGAL_INTERPRETATION: 0.05,
            K.MEASURED_QUANTITY: 1.0,
            K.PROJECTION: 0.3,
            K.ATTRIBUTION: 0.05,
            K.CAUSAL_EFFECT: 0.35,
            K.IMPLEMENTATION_STATUS: 0.5,
            K.PUBLIC_REACTION: 0.15,
        },
        incapable=[K.TEXTUAL_CONTENT, K.LEGAL_INTERPRETATION, K.ATTRIBUTION],
    ),
    EvidenceTier.PEER_REVIEWED: _capability(
        EvidenceTier.PEER_REVIEWED,
        "A reviewed study. The strongest available basis for a causal claim, and strictly "
        "bounded by its own design.",
        can=[
            "an identified effect under the stated design, population and period",
            "the conditions and assumptions the finding depends on",
            "what the literature has tested and what it has not",
            "the size of an effect with its stated uncertainty",
        ],
        cannot=[
            "transfer of a finding to a population, period or institutional setting the "
            "design did not cover",
            "what a specific instrument will do, absent a study of that instrument",
            "effects the design was not powered to detect",
            "what a text says or what an actor asserted",
        ],
        affinity={
            K.TEXTUAL_CONTENT: 0.15,
            K.FORMAL_PROCESS: 0.1,
            K.LEGAL_INTERPRETATION: 0.2,
            K.MEASURED_QUANTITY: 0.7,
            K.PROJECTION: 0.6,
            K.ATTRIBUTION: 0.1,
            K.CAUSAL_EFFECT: 0.85,
            K.IMPLEMENTATION_STATUS: 0.4,
            K.PUBLIC_REACTION: 0.2,
        },
        incapable=[K.TEXTUAL_CONTENT, K.FORMAL_PROCESS, K.ATTRIBUTION],
    ),
    EvidenceTier.EXPERT_ANALYSIS: _capability(
        EvidenceTier.EXPERT_ANALYSIS,
        "A reasoned interpretation. Useful for finding what to check; not itself a check.",
        can=[
            "a reasoned reading of evidence, with its assumptions made explicit",
            "identification of a mechanism, an omission or an inconsistency worth checking",
            "the existence and shape of a professional disagreement",
        ],
        cannot=[
            "settle a factual question by assertion",
            "establish an effect without the underlying data",
            "substitute its author's standing for evidence",
            "represent a field's consensus on its own",
        ],
        affinity={
            K.TEXTUAL_CONTENT: 0.2,
            K.FORMAL_PROCESS: 0.2,
            K.LEGAL_INTERPRETATION: 0.5,
            K.MEASURED_QUANTITY: 0.4,
            K.PROJECTION: 0.55,
            K.ATTRIBUTION: 0.3,
            K.CAUSAL_EFFECT: 0.5,
            K.IMPLEMENTATION_STATUS: 0.4,
            K.PUBLIC_REACTION: 0.25,
        },
    ),
    EvidenceTier.JOURNALISM: _capability(
        EvidenceTier.JOURNALISM,
        "A report of events and statements. Strong evidence that something was said or "
        "happened; weak evidence that a reported claim is true.",
        can=[
            "that a statement was made, in what role terms, when and where",
            "the existence and timing of a reported event",
            "the documents and sources the item names, quotes or links",
            "what was in public circulation at a given date",
        ],
        cannot=[
            "the truth of a claim it reports without grounding it",
            "a causal relation it asserts without cited evidence",
            "anything for which it is the sole and ungrounded source",
            "a measured quantity it did not measure",
        ],
        affinity={
            K.TEXTUAL_CONTENT: 0.25,
            K.FORMAL_PROCESS: 0.4,
            K.LEGAL_INTERPRETATION: 0.15,
            K.MEASURED_QUANTITY: 0.25,
            K.PROJECTION: 0.15,
            K.ATTRIBUTION: 0.9,
            K.CAUSAL_EFFECT: 0.15,
            K.IMPLEMENTATION_STATUS: 0.55,
            K.PUBLIC_REACTION: 0.85,
        },
        incapable=[K.CAUSAL_EFFECT],
    ),
    EvidenceTier.POLITICAL_STATEMENT: _capability(
        EvidenceTier.POLITICAL_STATEMENT,
        "An actor's own account. Definitive about what was claimed; no evidence at all that "
        "the claim is so.",
        can=[
            "what an actor publicly asserted or committed to, and when",
            "the position of record, for a later consistency check",
            "the framing and emphasis an actor chose",
        ],
        cannot=[
            "whether the assertion is true — to any degree whatsoever",
            "the effect of the measure being discussed",
            "any fact about the world beyond the fact of the utterance",
            "what a text says, as against what it is said to say",
        ],
        affinity={
            K.TEXTUAL_CONTENT: 0.1,
            K.FORMAL_PROCESS: 0.2,
            K.LEGAL_INTERPRETATION: 0.1,
            K.MEASURED_QUANTITY: 0.05,
            K.PROJECTION: 0.1,
            K.ATTRIBUTION: 1.0,
            K.CAUSAL_EFFECT: 0.05,
            K.IMPLEMENTATION_STATUS: 0.15,
            K.PUBLIC_REACTION: 0.6,
        },
        incapable=[
            K.MEASURED_QUANTITY,
            K.CAUSAL_EFFECT,
            K.TEXTUAL_CONTENT,
            K.LEGAL_INTERPRETATION,
        ],
    ),
    EvidenceTier.SOCIAL_MEDIA: _capability(
        EvidenceTier.SOCIAL_MEDIA,
        "A public post. Evidence that something circulated; evidence of little else.",
        can=[
            "that an account published a statement at a given time",
            "the circulation of a framing, a rumour or a document",
            "the existence of a visible public reaction",
        ],
        cannot=[
            "authorship or authenticity without independent corroboration",
            "the truth of any assertion made in it",
            "that any reaction is representative of anything",
            "any measured quantity",
        ],
        affinity={
            K.TEXTUAL_CONTENT: 0.05,
            K.FORMAL_PROCESS: 0.05,
            K.LEGAL_INTERPRETATION: 0.05,
            K.MEASURED_QUANTITY: 0.05,
            K.PROJECTION: 0.05,
            K.ATTRIBUTION: 0.7,
            K.CAUSAL_EFFECT: 0.03,
            K.IMPLEMENTATION_STATUS: 0.1,
            K.PUBLIC_REACTION: 0.7,
        },
        incapable=[
            K.MEASURED_QUANTITY,
            K.CAUSAL_EFFECT,
            K.TEXTUAL_CONTENT,
            K.LEGAL_INTERPRETATION,
            K.FORMAL_PROCESS,
        ],
    ),
}


def _validate_matrix() -> None:
    """Refuse to load a matrix that contradicts itself.

    A tier declared structurally incapable of a question while carrying a high
    affinity for it would produce a ranking whose explanation contradicted its
    own numbers, and the explanation is the product. Checked at import so the
    inconsistency cannot survive a commit.
    """
    missing = set(EvidenceTier) - set(TIER_CAPABILITIES)
    if missing:
        raise AssertionError(
            f"tier capability matrix is missing rows for {sorted(t.value for t in missing)}; "
            "every tier must state what it can and cannot establish"
        )
    for tier, capability in TIER_CAPABILITIES.items():
        for kind in capability.structurally_incapable:
            value = capability.affinity.get(kind, 0.0)
            if value > 0.2:
                raise AssertionError(
                    f"{tier.value} is declared structurally incapable of {kind.value} but "
                    f"carries affinity {value}; the table would rank an item high and then "
                    "explain that it cannot bear on the question"
                )
        if not capability.can_establish or not capability.cannot_establish:
            raise AssertionError(
                f"{tier.value} must state both what it can and what it cannot establish; a "
                "tier with an empty cannot_establish list has not been thought about"
            )


_validate_matrix()


def tier_capability_table() -> list[dict[str, Any]]:
    """Render the matrix as JSON-safe rows for an interface.

    Exists so the ranking is inspectable in the product rather than only in the
    source. A user who wants to know why a ministry press release sits below a
    statistical series for a question about a measured value gets the table, the
    two ``cannot_establish`` lists and the affinity numbers — and can disagree
    with the rule rather than with the ordering.
    """
    return [
        {
            "tier": tier.value,
            "summary": capability.summary,
            "can_establish": list(capability.can_establish),
            "cannot_establish": list(capability.cannot_establish),
            "structurally_incapable_of": sorted(k.value for k in capability.structurally_incapable),
            "affinity": {
                kind.value: capability.affinity_for(kind)
                for kind in QuestionKind
                if kind is not QuestionKind.UNKNOWN
            },
        }
        for tier, capability in sorted(TIER_CAPABILITIES.items(), key=lambda kv: kv[0].value)
    ]


# ---------------------------------------------------------------------------
# Question classification
# ---------------------------------------------------------------------------

_QUESTION_PATTERNS: Final[tuple[tuple[QuestionKind, re.Pattern[str]], ...]] = (
    (
        K.TEXTUAL_CONTENT,
        re.compile(
            r"\b(what does .{0,40}(say|state|provide|require)|text of|wording|verbatim"
            r"|does the (bill|text|document|instrument|provision)"
            r"|que dice|texto de|literal|tenor literal|redaccion)\b"
        ),
    ),
    (
        K.FORMAL_PROCESS,
        re.compile(
            r"\b(was it (passed|approved|voted|introduced|withdrawn)|when was .{0,40}"
            r"(voted|approved|introduced)|committee stage|first reading|quorum"
            r"|fue aprobad|se voto|tramitacion|votacion|comision de)\b"
        ),
    ),
    (
        K.MEASURED_QUANTITY,
        re.compile(
            r"\b(how much|how many|what (is|was) the (rate|level|value|figure|number|share"
            r"|percentage|total)|cuanto|cuantos|cual es (la|el) (tasa|cifra|nivel|monto)"
            r"|que porcentaje)\b"
        ),
    ),
    (
        K.CAUSAL_EFFECT,
        re.compile(
            r"\b(did .{0,40}(cause|lead to|result in|reduce|increase)|because of|as a result of"
            r"|effect of .{0,40} on|impact of .{0,40} on|attributable to"
            r"|provoco|causo|se debe a|efecto de .{0,40} sobre|impacto de .{0,40} en)\b"
        ),
    ),
    (
        K.PROJECTION,
        re.compile(
            r"\b(will|expected to|forecast|projected|estimate[sd]? that|is likely to|by 20\d\d"
            r"|se espera|se proyecta|proyeccion|estimacion|preve|hacia 20\d\d)\b"
        ),
    ),
    (
        K.ATTRIBUTION,
        re.compile(
            r"\b(who said|did .{0,40} say|claim(ed)? that|according to whom|stated that"
            r"|committed to|promised|quien dijo|afirmo que|sostuvo que|se comprometio)\b"
        ),
    ),
    (
        K.LEGAL_INTERPRETATION,
        re.compile(
            r"\b(does .{0,40} (apply|cover|permit|prohibit|oblige)|is .{0,40} lawful|legally"
            r"|interpretation of|scope of the (provision|article|section)"
            r"|se aplica a|alcance del articulo|es legal|obliga a)\b"
        ),
    ),
    (
        K.IMPLEMENTATION_STATUS,
        re.compile(
            r"\b(has .{0,40} been (implemented|published|issued|delivered|met)|on time"
            r"|by the deadline|still pending|did .{0,40} comply"
            r"|se implemento|se publico|se cumplio|plazo vencid|sigue pendiente)\b"
        ),
    ),
    (
        K.PUBLIC_REACTION,
        re.compile(
            r"\b(reaction|responded|criticis|support(ed)? by|opposed|backlash|public opinion"
            r"|reaccion|criticas|rechazo|apoyo de|opinion publica)\b"
        ),
    ),
)


def classify_question(question: str) -> QuestionKind:
    """Type a question so the right artefact classes rank above the wrong ones.

    A deterministic pattern match over English and Spanish phrasings — language
    coverage, not jurisdiction coverage; nothing here knows about a country, a
    body or a document. Returns :attr:`QuestionKind.UNKNOWN` when nothing matches,
    which produces a flat prior across tiers. That is the correct behaviour: an
    unclassified question is a reason for the ranking to be less opinionated, and
    the one thing it must not do is fall back on which tier sounds most
    authoritative.

    Patterns are tried most-specific first, and the first match wins.
    """
    text = _normalise(question)
    for kind, pattern in _QUESTION_PATTERNS:
        if pattern.search(text):
            return kind
    return QuestionKind.UNKNOWN


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RankConfig:
    """Component weights and penalties, all of them visible.

    Note what is not here and cannot be added: there is no per-source, per-outlet
    or per-institution weight, and no field one could be written into. The whole
    configuration surface of this module is six component weights and two
    penalties, none of which knows who published anything.
    """

    tier_affinity_weight: float = 30.0
    topical_relevance_weight: float = 22.0
    specificity_weight: float = 12.0
    quantitative_weight: float = 10.0
    recency_weight: float = 10.0
    corroboration_weight: float = 16.0

    incapable_multiplier: float = 0.2
    """Applied when the question is one the item's tier structurally cannot
    settle. A cap rather than a zero, because such an item is still worth showing
    — a political statement is exactly the right evidence for what was claimed,
    and the reader needs to see it sitting below the material that can settle the
    question, with the reason attached."""

    syndication_discount: float = 0.35
    """Reduction for an item that restates another. Republication adds reach, not
    evidence, and an evidence base ranked without this discount would put five
    copies of one report above the one study that tested it."""

    corroboration_saturation: int = 3
    """Independent corroborations at which the corroboration component maxes out.
    Deliberately low: the step from one source to two is the one that matters,
    and the step from nine to ten is nearly meaningless."""

    min_topical_overlap: float = 0.02
    """Below this, an item is reported as off-question rather than ranked."""


DEFAULT_RANK_CONFIG: Final[RankConfig] = RankConfig()


# ---------------------------------------------------------------------------
# The scoring view — where the prohibition is made structural
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ScoringView:
    """Everything the scorer is allowed to see, and nothing else.

    The structural half of Aleph's independence-from-authority rule, built on the
    same principle as
    :class:`~aleph.core.models.RedactedClaimContext`: a prohibition that lives in
    a type cannot be forgotten. There is no publisher, no outlet name, no
    institution, no title and no URL on this object, and ``frozen=True`` with
    ``slots=True`` means none can be attached to it later.

    ``source_token`` is a hash of the source identity. It exists solely so that
    corroboration counting can ask whether two items came from the same place. It
    cannot be looked up, sorted meaningfully, or matched against any table of
    sources, because it is a digest — so the only operation available on it is the
    only one that is legitimate.
    """

    evidence_id: str
    tier: EvidenceTier
    statement: str
    span_text: str
    retrieved_at: str
    published_at: str | None
    quantity_count: int
    money_count: int
    declared_question: str
    declared_relevance: float
    independence: Independence | None
    derived_from: str | None
    supports: frozenset[str]
    contradicts: frozenset[str]
    source_token: str
    content_key: str
    """Hash of the statement. The tie-break, so that not even alphabetical order
    over ids — which carry outlet slugs — can influence a position."""

    @classmethod
    def of(cls, item: EvidenceItem) -> _ScoringView:
        return cls(
            evidence_id=item.id,
            tier=item.tier,
            statement=item.statement,
            span_text=" ".join(span.text for span in item.spans),
            retrieved_at=item.retrieved_at,
            published_at=item.source_ref.published_at,
            quantity_count=len(item.quantities),
            money_count=len(item.money),
            declared_question=item.evidential_relevance.question,
            declared_relevance=item.evidential_relevance.relevance,
            independence=item.independence,
            derived_from=item.derived_from_evidence_id,
            supports=frozenset(item.supports),
            contradicts=frozenset(item.contradicts),
            source_token=stable_hash("source", item.source_ref.id, length=16),
            content_key=stable_hash(_normalise(item.statement), length=16),
        )


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RankedEvidence:
    """One item's position, with the full arithmetic that produced it."""

    item: EvidenceItem
    rank: int
    score: float
    """0-100. Position among these items for THIS question. Not a quality
    rating, and meaningless detached from the question."""
    components: tuple[Component, ...]
    """Every contribution, with its points. Sums to ``score`` before caps."""
    capability: TierCapability
    caps_applied: tuple[str, ...]
    explanation: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "evidence_id": self.item.id,
            "rank": self.rank,
            "score": self.score,
            "tier": self.item.tier.value,
            "components": [c.to_jsonable() for c in self.components],
            "can_establish": list(self.capability.can_establish),
            "cannot_establish": list(self.capability.cannot_establish),
            "caps_applied": list(self.caps_applied),
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class EvidenceRanking:
    """The ordered evidence for one question, plus what was left out and why."""

    question: str
    question_kind: QuestionKind
    ranked: tuple[RankedEvidence, ...]
    excluded: tuple[tuple[str, str], ...]
    """``(evidence_id, reason)`` for items that did not bear on the question at
    all. Published rather than dropped: what a search found and discarded is part
    of knowing how thorough it was."""
    config: RankConfig = DEFAULT_RANK_CONFIG
    independent_source_count: int = 0

    @property
    def items(self) -> tuple[EvidenceItem, ...]:
        return tuple(r.item for r in self.ranked)

    def top(self, n: int) -> tuple[RankedEvidence, ...]:
        return self.ranked[:n]

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "question_kind": self.question_kind.value,
            "independent_source_count": self.independent_source_count,
            "ranked": [r.to_jsonable() for r in self.ranked],
            "excluded": [{"evidence_id": i, "reason": r} for i, r in self.excluded],
        }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-z]+(?:[.,][0-9]+)*")
_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"\d")
_SCOPE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(19\d\d|20\d\d|between|from .{0,20} to |per (year|month|capita)|excluding|excepto"
    r"|entre|desde .{0,20} hasta |anual|mensual|per capita|salvo)\b"
)


def _normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WS_RE.sub(" ", stripped.lower()).strip()


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(_normalise(text))


def _parse_instant(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text[:-1]).replace(tzinfo=UTC)
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _topical_relevance(
    view: _ScoringView, question_tokens: set[str], idf: Mapping[str, float]
) -> float:
    """IDF-weighted overlap between the question and the item's own words.

    Weighted by inverse document frequency over the candidate set so that a term
    every item shares — the subject everyone is talking about — cannot make every
    item look equally on-point. What distinguishes items is the rare terms they
    share with the question.

    An item's own recorded ``evidential_relevance`` is folded in when it was
    assessed against this same question, because the retriever knew something the
    token overlap cannot see. It is a contribution, never an override: a
    self-declared relevance of 1.0 on an item with no lexical bearing at all
    should not carry the item.
    """
    if not question_tokens:
        return 0.0
    item_tokens = set(_tokens(f"{view.statement} {view.span_text}"))
    overlap = question_tokens & item_tokens
    weighted = sum(idf.get(token, 1.0) for token in overlap)
    total = sum(idf.get(token, 1.0) for token in question_tokens) or 1.0
    lexical = weighted / total

    declared = 0.0
    if _normalise(view.declared_question) == _normalise(" ".join(sorted(question_tokens))):
        declared = view.declared_relevance
    return min(1.0, 0.75 * lexical + 0.25 * declared) if declared else min(1.0, lexical)


def _specificity(view: _ScoringView) -> float:
    """How far the item pins its statement down.

    A statement carrying a figure, a period and a quotable passage of real length
    can be checked. "Experts say the measure will help" cannot be checked at all,
    and an evidence base that ranked it alongside a costed estimate would be
    telling the reader something false about how much is known.
    """
    text = f"{view.statement} {view.span_text}"
    tokens = _tokens(text)
    if not tokens:
        return 0.0
    numeric = sum(1 for t in tokens if _NUMBER_RE.search(t))
    numeric_density = min(1.0, numeric / 8.0)
    scope = 1.0 if _SCOPE_RE.search(_normalise(text)) else 0.0
    # Verbatim passage length, saturating: past a couple of hundred words more
    # text stops being more precision.
    passage = min(1.0, len(_tokens(view.span_text)) / 120.0)
    return round(0.4 * numeric_density + 0.25 * scope + 0.35 * passage, 4)


def _quantitative_content(view: _ScoringView) -> float:
    """Structured numeric content: extracted quantities and money."""
    return min(1.0, (view.quantity_count + view.money_count) / 3.0)


def _recency(view: _ScoringView, as_of: datetime, half_life_days: float) -> float:
    """Exponential decay in age, measured from publication where it is known.

    Falls back to retrieval time, and to a neutral 0.5 when neither parses:
    unknown age is an absence of information about age, and scoring it as ancient
    would demote every item whose source omitted a date.
    """
    when = _parse_instant(view.published_at) or _parse_instant(view.retrieved_at)
    if when is None:
        return 0.5
    age_days = max(0.0, (as_of - when).total_seconds() / 86400.0)
    return math.exp(-math.log(2) * age_days / max(half_life_days, 1e-6))


def _corroboration(
    view: _ScoringView, views: Sequence[_ScoringView], config: RankConfig
) -> tuple[float, int]:
    """How many other items independently say something compatible.

    An item corroborates another when it comes from a different source, neither
    derives from the other, it does not declare itself a restatement, and it
    either bears on the same claim or shares substantial vocabulary. Distinct
    *sources* are counted, not items, because two pieces from one newsroom are one
    observation — the same rule :mod:`aleph.news.independence` applies to
    articles, applied here to evidence.

    Returns ``(score, distinct_corroborating_sources)``.
    """
    restating = {Independence.SYNDICATED, Independence.DERIVATIVE, Independence.AGGREGATED}
    own_tokens = set(_tokens(view.statement))
    sources: set[str] = set()
    for other in views:
        if other.evidence_id == view.evidence_id or other.source_token == view.source_token:
            continue
        if other.derived_from == view.evidence_id or view.derived_from == other.evidence_id:
            continue
        if other.independence in restating:
            continue
        shares_claim = bool(
            (view.supports & other.supports) or (view.contradicts & other.contradicts)
        )
        other_tokens = set(_tokens(other.statement))
        union = own_tokens | other_tokens
        lexical = len(own_tokens & other_tokens) / len(union) if union else 0.0
        if shares_claim or lexical >= 0.25:
            sources.add(other.source_token)
    count = len(sources)
    return min(1.0, count / max(1, config.corroboration_saturation)), count


def rank_evidence(
    question: str,
    items: Sequence[EvidenceItem],
    *,
    question_kind: QuestionKind | None = None,
    as_of: datetime | str | None = None,
    config: RankConfig = DEFAULT_RANK_CONFIG,
) -> EvidenceRanking:
    """Order evidence by what it can settle about THIS question.

    Args:
        question: The question the evidence is being assembled for. Ranking has
            no meaning without one — an item is not "good evidence", it is good
            evidence *for something*.
        items: Candidates. Input order does not affect the result; the
            ``evidence_order_shuffle`` neutrality perturbation depends on that.
        question_kind: Override the classifier when the caller already knows.
        as_of: Reference instant for recency. Defaults to now. Pass a fixed value
            for a reproducible ranking.
        config: Component weights and penalties.

    Returns:
        An :class:`EvidenceRanking` in which every position is explained by its
        components, and items that bear on the question not at all are listed
        separately with the reason.
    """
    kind = question_kind or classify_question(question)
    reference = _reference_instant(as_of)
    views = [_ScoringView.of(item) for item in items]
    by_id = {item.id: item for item in items}

    question_tokens = set(_tokens(question))
    idf = _inverse_document_frequency(views, question_tokens)

    half_life = QUESTION_RECENCY_HALF_LIFE.get(kind)
    quantitativeness = QUESTION_QUANTITATIVENESS.get(kind, 0.4)

    scored: list[tuple[float, str, RankedEvidence]] = []
    excluded: list[tuple[str, str]] = []
    corroborating_sources: set[str] = set()

    for view in views:
        capability = TIER_CAPABILITIES[view.tier]
        affinity = capability.affinity_for(kind)
        topical = _topical_relevance(view, question_tokens, idf)

        if topical < config.min_topical_overlap and affinity < 0.3:
            excluded.append(
                (
                    view.evidence_id,
                    f"no lexical bearing on the question and its tier ({view.tier.value}) "
                    f"bears weakly on {kind.value} questions",
                )
            )
            continue

        specificity = _specificity(view)
        quantitative = _quantitative_content(view) * quantitativeness
        corroboration, corroborators = _corroboration(view, views, config)
        if corroborators:
            corroborating_sources.add(view.source_token)

        applicable: list[tuple[str, float, float, str]] = [
            (
                "tier_question_affinity",
                config.tier_affinity_weight,
                affinity,
                f"a {view.tier.value} bears on a {kind.value} question at {affinity:.2f}: "
                f"{capability.summary}",
            ),
            (
                "topical_relevance",
                config.topical_relevance_weight,
                topical,
                "IDF-weighted overlap between the question's terms and the item's own "
                "statement and quoted passages",
            ),
            (
                "specificity",
                config.specificity_weight,
                specificity,
                "how far the item pins down a figure, a period and a quotable passage",
            ),
            (
                "independent_corroboration",
                config.corroboration_weight,
                corroboration,
                f"{corroborators} other source(s) in this set say something compatible "
                "without restating this item",
            ),
        ]
        if quantitativeness > 0.0:
            applicable.append(
                (
                    "quantitative_content",
                    config.quantitative_weight,
                    quantitative,
                    "extracted quantities and monetary values, scaled by how numeric the "
                    "question is",
                )
            )
        if half_life is not None:
            applicable.append(
                (
                    "recency",
                    config.recency_weight,
                    _recency(view, reference, half_life),
                    f"age, with a {half_life:.0f}-day half-life for {kind.value} questions",
                )
            )

        # Inapplicable components are dropped and their weight redistributed
        # rather than scored as zero. Scoring recency as zero for a question about
        # what a text says would penalise every primary document for being old,
        # which is the opposite of correct.
        weight_total = sum(weight for _, weight, _, _ in applicable) or 1.0
        scale = 100.0 / weight_total

        components: list[Component] = []
        raw = 0.0
        for label, weight, value, note in applicable:
            points = weight * scale * value
            raw += points
            components.append(
                Component(
                    label=label,
                    direction=Direction.POSITIVE if value > 0 else Direction.NONE,
                    weight=round(points, 2),
                    evidence_refs=[view.evidence_id],
                    note=note,
                )
            )

        caps: list[str] = []
        score = raw
        if kind in capability.structurally_incapable:
            score *= config.incapable_multiplier
            caps.append(
                f"capped to {config.incapable_multiplier:.0%}: a {view.tier.value} is "
                f"structurally incapable of settling a {kind.value} question. It may still "
                "be the right evidence for a different question about the same subject."
            )
            components.append(
                Component(
                    label="tier_capability_cap",
                    direction=Direction.NEGATIVE,
                    weight=round(max(-100.0, score - raw), 2),
                    evidence_refs=[view.evidence_id],
                    note=capability.cannot_establish[0],
                )
            )
        if view.derived_from or view.independence in {
            Independence.SYNDICATED,
            Independence.DERIVATIVE,
            Independence.AGGREGATED,
        }:
            before = score
            score *= 1.0 - config.syndication_discount
            caps.append(
                f"discounted {config.syndication_discount:.0%}: this item restates another "
                "rather than observing independently, and republication adds reach, not "
                "evidence"
            )
            components.append(
                Component(
                    label="syndication_discount",
                    direction=Direction.NEGATIVE,
                    weight=round(max(-100.0, score - before), 2),
                    evidence_refs=[view.evidence_id],
                    note=(
                        f"restates {view.derived_from}"
                        if view.derived_from
                        else f"declared independence: {view.independence}"
                    ),
                )
            )

        scored.append(
            (
                -round(score, 6),
                view.content_key,
                RankedEvidence(
                    item=by_id[view.evidence_id],
                    rank=0,
                    score=round(score, 2),
                    components=tuple(components),
                    capability=capability,
                    caps_applied=tuple(caps),
                    explanation=_explain(
                        kind, capability, components, caps, corroborators, view.tier
                    ),
                ),
            )
        )

    scored.sort(key=lambda entry: (entry[0], entry[1]))
    ranked = tuple(
        RankedEvidence(
            item=entry[2].item,
            rank=position + 1,
            score=entry[2].score,
            components=entry[2].components,
            capability=entry[2].capability,
            caps_applied=entry[2].caps_applied,
            explanation=entry[2].explanation,
        )
        for position, entry in enumerate(scored)
    )

    return EvidenceRanking(
        question=question,
        question_kind=kind,
        ranked=ranked,
        excluded=tuple(sorted(excluded)),
        config=config,
        independent_source_count=_independent_source_count(views),
    )


def _reference_instant(as_of: datetime | str | None) -> datetime:
    if isinstance(as_of, datetime):
        return as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    if isinstance(as_of, str):
        parsed = _parse_instant(as_of)
        if parsed is not None:
            return parsed
    return datetime.now(UTC)


def _inverse_document_frequency(
    views: Sequence[_ScoringView], question_tokens: set[str]
) -> dict[str, float]:
    """IDF over the candidate set, for the question's terms only."""
    total = len(views) or 1
    frequency: dict[str, int] = {}
    for view in views:
        tokens = set(_tokens(f"{view.statement} {view.span_text}")) & question_tokens
        for token in tokens:
            frequency[token] = frequency.get(token, 0) + 1
    return {
        token: math.log((1 + total) / (1 + frequency.get(token, 0))) + 1.0
        for token in question_tokens
    }


def _independent_source_count(views: Sequence[_ScoringView]) -> int:
    """Distinct originating sources, excluding items that restate another.

    The number an evidence set may use to raise confidence — never the item
    count. Ten copies of one report are ten items and one source.
    """
    restating = {Independence.SYNDICATED, Independence.DERIVATIVE, Independence.AGGREGATED}
    return len(
        {
            view.source_token
            for view in views
            if view.derived_from is None and view.independence not in restating
        }
    )


def _explain(
    kind: QuestionKind,
    capability: TierCapability,
    components: Sequence[Component],
    caps: Sequence[str],
    corroborators: int,
    tier: EvidenceTier,
) -> str:
    """One paragraph a reader can argue with, naming no publisher."""
    positive = sorted((c for c in components if c.weight > 0), key=lambda c: -c.weight)
    drivers = ", ".join(f"{c.label} (+{c.weight:.0f})" for c in positive[:3])
    lines = [
        f"Ranked for a {kind.value} question. Strongest contributors: {drivers}.",
        f"A {tier.value} can establish: {capability.can_establish[0]}.",
        f"It cannot establish: {capability.cannot_establish[0]}.",
    ]
    if corroborators:
        lines.append(f"{corroborators} other independent source(s) here say something compatible.")
    else:
        lines.append("No other independent source in this set corroborates it.")
    lines.extend(caps)
    lines.append(
        "Position reflects what this class of artefact can settle about this question. "
        "Who published it was not an input."
    )
    return " ".join(lines)


# ---------------------------------------------------------------------------
# The invariance check — the rule, tested rather than promised
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorityInvarianceReport:
    """Result of re-ranking with every publisher identity permuted.

    The rule this module is built around says outlet and institutional standing
    must not influence a ranking. That is a testable proposition, so it is tested
    rather than asserted: if the order changes when only the publishers change,
    authority leaked in somewhere and the report says where.
    """

    passed: bool
    question: str
    original_order: tuple[str, ...]
    permuted_order: tuple[str, ...]
    anonymised_order: tuple[str, ...]
    note: str

    def raise_if_failed(self) -> None:
        """For a CI gate that must block a release.

        Raises:
            AssertionError: If the ranking moved. This is a defect in Aleph, not
                a property of the data: nothing evidentially relevant changed.
        """
        if not self.passed:
            raise AssertionError(self.note)


def authority_invariance_check(
    question: str,
    items: Sequence[EvidenceItem],
    *,
    question_kind: QuestionKind | None = None,
    as_of: datetime | str | None = None,
    config: RankConfig = DEFAULT_RANK_CONFIG,
) -> AuthorityInvarianceReport:
    """Re-rank with publishers permuted and with them removed, and compare.

    Two transformations, both of which leave every evidentially relevant property
    untouched:

    1. **Permutation.** Publisher names and source ids are rotated by one, so
       every item keeps a distinct source identity — corroboration counting still
       works — but each is attributed to a different publisher.
    2. **Anonymisation.** Every publisher name and title is replaced by a
       placeholder, while source ids stay distinct.

    If either changes the order, some path from publisher identity to score
    exists. Because :class:`_ScoringView` has nowhere to put a publisher, that
    should be impossible — and this function is what turns "should be" into
    "checked, on this data, on this run".

    Note that ``as_of`` is pinned across the three runs, so a clock tick between
    them cannot masquerade as a violation.
    """
    reference = _reference_instant(as_of)
    baseline = rank_evidence(
        question, items, question_kind=question_kind, as_of=reference, config=config
    )

    permuted = _permute_publishers(items)
    anonymised = _anonymise_publishers(items)

    permuted_ranking = rank_evidence(
        question, permuted, question_kind=question_kind, as_of=reference, config=config
    )
    anonymous_ranking = rank_evidence(
        question, anonymised, question_kind=question_kind, as_of=reference, config=config
    )

    original_order = tuple(r.item.id for r in baseline.ranked)
    permuted_order = tuple(r.item.id for r in permuted_ranking.ranked)
    anonymised_order = tuple(r.item.id for r in anonymous_ranking.ranked)

    passed = original_order == permuted_order == anonymised_order
    if passed:
        note = (
            f"Ranking for {question!r} is invariant under publisher permutation and "
            f"anonymisation across {len(original_order)} item(s): no path from publisher "
            "identity to position exists."
        )
    else:
        note = (
            f"AUTHORITY LEAK: the ranking for {question!r} changed when only publisher "
            f"identity changed. baseline={original_order} permuted={permuted_order} "
            f"anonymised={anonymised_order}. Nothing evidentially relevant was altered, so "
            "this is a defect in Aleph's ranking path."
        )
    return AuthorityInvarianceReport(
        passed=passed,
        question=question,
        original_order=original_order,
        permuted_order=permuted_order,
        anonymised_order=anonymised_order,
        note=note,
    )


def _permute_publishers(items: Sequence[EvidenceItem]) -> list[EvidenceItem]:
    """Rotate publisher identity by one, keeping identities distinct.

    Distinctness is preserved because it is evidentially relevant: how many
    *different* sources an item is corroborated by is a real property, and
    collapsing them would change the ranking for a legitimate reason and make the
    test meaningless.
    """
    if len(items) < 2:
        return list(items)
    sources = [item.source_ref for item in items]
    rotated = sources[1:] + sources[:1]
    out: list[EvidenceItem] = []
    for item, other in zip(items, rotated, strict=True):
        out.append(
            item.model_copy(
                update={
                    "source_ref": item.source_ref.model_copy(
                        update={
                            "publisher": other.publisher,
                            "title": other.title,
                            "url": other.url,
                        }
                    )
                }
            )
        )
    return out


def _anonymise_publishers(items: Sequence[EvidenceItem]) -> list[EvidenceItem]:
    """Strip publisher names and titles entirely, keeping source ids distinct."""
    return [
        item.model_copy(
            update={
                "source_ref": item.source_ref.model_copy(
                    update={
                        "publisher": None,
                        "title": f"source {index}",
                        "url": None,
                    }
                )
            }
        )
        for index, item in enumerate(items)
    ]


# ---------------------------------------------------------------------------
# From a ranking to a publishable evidence set
# ---------------------------------------------------------------------------


def evidence_strength_for(ranking: EvidenceRanking) -> EvidenceStrength:
    """How much weight the assembled evidence can bear for this question.

    Governed by two things and deliberately not by three. The top item must be
    able to *settle* the question — a set whose best member is structurally
    incapable of the question cannot be strong however many members it has — and
    there must be independent corroboration. Volume is not one of the two.
    ``insufficient`` is a real and publishable result, reached whenever nothing
    survived that bears on the question at all.
    """
    if not ranking.ranked:
        return EvidenceStrength.INSUFFICIENT
    best = ranking.ranked[0]
    capable = ranking.question_kind not in best.capability.structurally_incapable
    sources = ranking.independent_source_count

    if capable and best.score >= 55.0 and sources >= 2:
        return EvidenceStrength.HIGH
    if capable and best.score >= 35.0 and sources >= 1:
        return EvidenceStrength.MEDIUM
    if best.score >= 20.0:
        return EvidenceStrength.LOW
    return EvidenceStrength.INSUFFICIENT


def to_evidence_set(ranking: EvidenceRanking, set_id: str) -> EvidenceSet:
    """Render a ranking as the publishable contract object.

    ``independent_source_count`` is carried separately from the member count on
    purpose, and the summary states both, because they are the two numbers a
    reader needs side by side to avoid reading loudness as agreement.
    """
    strength = evidence_strength_for(ranking)
    gaps = _named_gaps(ranking)
    top = ranking.ranked[0] if ranking.ranked else None

    summary = (
        f"{len(ranking.ranked)} item(s) bearing on a {ranking.question_kind.value} question, "
        f"from {ranking.independent_source_count} independent source(s). "
        + (
            f"The highest-ranked is a {top.item.tier.value}, which can establish "
            f"{top.capability.can_establish[0]}."
            if top
            else "Nothing retrieved bears on this question."
        )
    )

    return EvidenceSet(
        id=set_id,
        question=ranking.question,
        evidence_ids=[r.item.id for r in ranking.ranked],
        strength=strength,
        independent_source_count=ranking.independent_source_count,
        gaps=gaps,
        summary=summary,
        confidence=Confidence(
            evidence_confidence=_set_confidence(ranking, strength),
            basis=[
                ConfidenceBasis(
                    factor=ConfidenceFactor.SOURCE_INDEPENDENCE,
                    effect=(
                        ConfidenceEffect.RAISES
                        if ranking.independent_source_count > 1
                        else ConfidenceEffect.LOWERS
                    ),
                    note=(
                        f"{len(ranking.ranked)} item(s) from "
                        f"{ranking.independent_source_count} independent source(s)"
                    ),
                ),
                ConfidenceBasis(
                    factor=ConfidenceFactor.RETRIEVAL_COMPLETENESS,
                    effect=(ConfidenceEffect.LOWERS if gaps else ConfidenceEffect.NEUTRAL),
                    note=(
                        f"{len(gaps)} named gap(s) remain"
                        if gaps
                        else "no structural gap identified for this question kind"
                    ),
                ),
            ],
            limiting_factor=gaps[0] if gaps else None,
        ),
    )


def _named_gaps(ranking: EvidenceRanking) -> list[str]:
    """What is missing, stated as something a retriever could go and get."""
    gaps: list[str] = []
    if not ranking.ranked:
        gaps.append(
            f"No retrieved item bears on this {ranking.question_kind.value} question at all."
        )
        return gaps
    capable = [
        r
        for r in ranking.ranked
        if ranking.question_kind not in r.capability.structurally_incapable
    ]
    if not capable:
        wanted = sorted(
            tier.value
            for tier, capability in TIER_CAPABILITIES.items()
            if capability.affinity_for(ranking.question_kind) >= 0.6
        )
        gaps.append(
            "No item is of a class that can settle this question; every candidate is "
            f"structurally incapable of it. Wanted: {', '.join(wanted) or 'a more direct source'}."
        )
    if ranking.independent_source_count < 2:
        gaps.append(
            "Only one independent source underlies this set: nothing here is corroborated "
            "by a second observation."
        )
    if ranking.excluded:
        gaps.append(
            f"{len(ranking.excluded)} retrieved item(s) were found to bear on the question "
            "not at all, which may indicate the search vocabulary was off-target."
        )
    return gaps


def _set_confidence(ranking: EvidenceRanking, strength: EvidenceStrength) -> float:
    """Evidence confidence for the set, capped by independence rather than volume."""
    base = {
        EvidenceStrength.HIGH: 0.82,
        EvidenceStrength.MEDIUM: 0.6,
        EvidenceStrength.LOW: 0.38,
        EvidenceStrength.INSUFFICIENT: 0.12,
    }[strength]
    independence_cap = min(1.0, 0.3 + 0.25 * ranking.independent_source_count)
    return round(min(base, independence_cap), 3)
