"""Deciding whether a claim is true, and then — separately — who said it.

Aleph's evaluation is deliberately split in two, and the split is the product.

**Stage one** is :func:`evaluate_blind`. It receives a
:class:`~aleph.core.models.RedactedClaimContext` and nothing else — a frozen,
closed object with no field for a speaker, a party, a coalition, a
government-or-opposition status or an outlet. It applies the ten epistemic checks
as ten *individually recorded* results, and then derives a verdict from those
results with :func:`derive_verdict`, an ordinary readable function whose rules
are named and enumerable. There is no step at which a model is asked for a
label. That matters: a bare verdict from a model is unarguable, unreproducible,
and impossible to disagree with in part. A verdict assembled from ten checks can
be attacked at exactly the check a reader thinks is wrong, and the other nine
stand.

**Stage two** is :func:`analyse_attributed`. It restores provenance and looks at
framing, historical consistency and rhetorical pattern — the things a reader
legitimately wants and that must never touch a truth judgement. It takes the
:class:`~aleph.core.models.BlindEvaluation` as frozen input, returns a separate
object, and :func:`assert_verdict_preserved` raises
:class:`~aleph.core.errors.NeutralityViolationError` if the blind result moved by
so much as a rounding. The guard is not decoration: it is the runtime proof that
naming the speaker changed nothing.

Three rules are enforced structurally rather than by convention.

*Forecasts are never graded true.* A statement about the future yields
``forecast_conditional`` and publishes the assumptions it depends on. Marking a
projection ``supported`` would tell a reader the future had been audited.

*Opinions and normative claims get ``not_a_factual_claim``.* Not ``unsupported``
— which would read as a refutation of something never offered as a finding.

*Confidence comes from evidence, never from the model.*
:func:`compute_evidence_confidence` is arithmetic over primary-source coverage,
agreement, corroboration by genuinely independent sources, quantitative
validation and temporal consistency, with every contributing factor recorded in
:attr:`~aleph.core.models.Confidence.basis`. A provider's self-report is stored
in ``model_confidence`` as a diagnostic and is never read by that function. High
model confidence over one paywalled headline is a fact about the model.

One further commitment runs through the checks: **source authority is not
evidential weight**. Tier is consulted only for *applicability* — a primary
document can establish what a text says; a statistical dataset can bear on a
causal question — and never as a ranking of who to believe. Where the checks need
to compare two conflicting items, :func:`evidential_weight` uses assessed
strength, relevance to this question, whether a quotable passage exists, and
independence. Publisher standing appears nowhere in it, and by the time evidence
reaches this module the publisher has been pseudonymised out anyway.

Everything here runs offline and deterministically. ``provider`` is optional
everywhere; :class:`~aleph.claims.extract.DeterministicClaimProvider` is a real
working implementation, and with no provider at all the evaluator simply records
``model_confidence`` as ``None``, which is the honest value.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from aleph.actors.guard import assert_blind_input
from aleph.claims.blind import (
    Blinding,
    IdentityVocabulary,
    RedactionPolicy,
    blind_claim,
)
from aleph.claims.classify import ClaimClassification, classify_claim_text
from aleph.claims.extract import (
    ClaimLLMProvider,
    ExtractedClaim,
    ParsedNumber,
    absolute_value,
    parse_numbers,
)
from aleph.core.enums import (
    EPISTEMIC_CHECKS,
    CheckOutcome,
    ConfidenceEffect,
    ConfidenceFactor,
    EpistemicCheck,
    EvidenceStrength,
    EvidenceTier,
    HistoricalConsistencyAssessment,
    Independence,
    RhetoricalPattern,
    StatementType,
    UncertaintyKind,
    Verdict,
)
from aleph.core.errors import NeutralityViolationError
from aleph.core.ids import actor_id as make_actor_id
from aleph.core.ids import slugify
from aleph.core.models import (
    AttributedAnalysis,
    BlindEvaluation,
    Claim,
    Confidence,
    ConfidenceBasis,
    EpistemicCheckResult,
    EvidenceItem,
    HistoricalConsistency,
    RedactedClaimContext,
    RhetoricalObservation,
    Uncertainty,
)

__all__ = [
    "EVALUATOR_VERSION",
    "ATTRIBUTION_ANALYSER_VERSION",
    "CORE_CHECKS",
    "SUPPORTING_CHECKS",
    "DOCUMENTARY_TIERS",
    "ANALYTICAL_TIERS",
    "EvidenceView",
    "QuantitativeFinding",
    "VerdictDerivation",
    "ClaimEvaluation",
    "evidential_weight",
    "run_checks",
    "derive_verdict",
    "compute_evidence_confidence",
    "evaluate_blind",
    "analyse_attributed",
    "assert_verdict_preserved",
    "build_claim",
    "evaluate_claim",
]

#: Identifier and version of the blind evaluator, recorded on every evaluation so
#: a verdict can be reproduced or invalidated when the rules change.
EVALUATOR_VERSION: Final[str] = "aleph-blind-evaluator/1.0.0"

#: Version of the stage-two attributed analyser. Separate on purpose: the two
#: stages must be independently versionable, and a change to framing analysis
#: must never look like a change to a verdict.
ATTRIBUTION_ANALYSER_VERSION: Final[str] = "aleph-attributed-analyser/1.0.0"

#: Checks whose failure attacks the claim itself.
CORE_CHECKS: Final[tuple[EpistemicCheck, ...]] = (
    EpistemicCheck.DIRECT_TEXTUAL_EVIDENCE,
    EpistemicCheck.QUANTITATIVE_CORRECTNESS,
    EpistemicCheck.LOGICAL_VALIDITY,
    EpistemicCheck.TEMPORAL_CORRECTNESS,
    EpistemicCheck.CONTRADICTION_WITH_STRONGER_EVIDENCE,
)

#: Checks whose failure qualifies a claim without refuting it. A claim can be
#: perfectly true and still be delivered without its assumptions, without
#: corroboration, or shorn of context — findings a reader needs, and reasons to
#: say "partially supported" rather than "unsupported".
SUPPORTING_CHECKS: Final[tuple[EpistemicCheck, ...]] = tuple(
    check for check in EPISTEMIC_CHECKS if check not in CORE_CHECKS
)

#: Tiers that can establish what a text or a dataset SAYS.
#:
#: Used for applicability, never as a ranking. A primary document settles what an
#: instrument states and settles nothing about whether its projections will hold.
DOCUMENTARY_TIERS: Final[frozenset[EvidenceTier]] = frozenset(
    {
        EvidenceTier.PRIMARY_DOCUMENT,
        EvidenceTier.LEGISLATIVE_RECORD,
        EvidenceTier.OFFICIAL_TECHNICAL_REPORT,
        EvidenceTier.STATISTICAL_DATASET,
    }
)

#: Tiers that can bear on a CAUSAL question, because they carry a method.
#:
#: Again applicability, not prestige: journalism can report that an effect was
#: observed, but a causal claim needs something that says how the effect was
#: identified.
ANALYTICAL_TIERS: Final[frozenset[EvidenceTier]] = frozenset(
    {
        EvidenceTier.PEER_REVIEWED,
        EvidenceTier.EXPERT_ANALYSIS,
        EvidenceTier.OFFICIAL_TECHNICAL_REPORT,
        EvidenceTier.STATISTICAL_DATASET,
    }
)

#: Independence values that make an item a restatement rather than an observation.
_DEPENDENT_INDEPENDENCE: Final[frozenset[Independence]] = frozenset(
    {Independence.SYNDICATED, Independence.DERIVATIVE, Independence.AGGREGATED}
)

_STRENGTH_WEIGHT: Final[Mapping[EvidenceStrength, float]] = {
    EvidenceStrength.HIGH: 1.0,
    EvidenceStrength.MEDIUM: 0.65,
    EvidenceStrength.LOW: 0.35,
    EvidenceStrength.INSUFFICIENT: 0.1,
}

#: Relative tolerance when comparing two figures for agreement. Half a per cent
#: absorbs rounding and unit conversion without absorbing a real discrepancy.
NUMERIC_TOLERANCE: Final[float] = 0.005

#: Absolute tolerance, in percentage points, for a re-derived percentage.
PERCENT_POINT_TOLERANCE: Final[float] = 0.5

_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "and",
        "to",
        "in",
        "that",
        "is",
        "are",
        "was",
        "were",
        "for",
        "with",
        "on",
        "as",
        "by",
        "from",
        "it",
        "this",
        "these",
        "be",
        "been",
        "will",
        "would",
        "has",
        "have",
        "had",
        "not",
        "or",
        "but",
        "at",
        "its",
        "their",
        "which",
        "than",
        "then",
        "so",
        "if",
        "when",
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "de",
        "del",
        "y",
        "que",
        "en",
        "por",
        "para",
        "con",
        "se",
        "es",
        "son",
        "fue",
        "fueron",
        "no",
        "al",
        "como",
        "mas",
        "pero",
        "su",
        "sus",
        "lo",
        "le",
        "ya",
        "sobre",
        "entre",
        "sera",
        "seran",
        "ha",
        "han",
        "esta",
        "este",
        "esto",
    }
)

_NEGATION_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:not|no|never|neither|nor|without|fails?\s+to|did\s+not|does\s+not|"
    r"nunca|jam[aá]s|ning[uú]n[oa]?|sin|tampoco|no\s+se)\b",
    re.IGNORECASE,
)
_MECHANISM_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:mechanism|mecanismo|because|porque|via|v[ií]a|through|mediante|"
    r"a\s+trav[eé]s\s+de|channel|canal|pathway|identification\s+strategy|"
    r"counterfactual|contrafactual|control\s+group|grupo\s+de\s+control)\b",
    re.IGNORECASE,
)
_CONCLUSION_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:therefore|thus|hence|so\s+that|it\s+follows|consequently|"
    r"por\s+lo\s+tanto|por\s+tanto|as[ií]\s+que|en\s+consecuencia|de\s+modo\s+que)\b",
    re.IGNORECASE,
)
_PERIOD_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:19|20|21)\d{2}\b|\b(?:since|from|between|over\s+the|compared\s+(?:with|to)|"
    r"year[-\s]on[-\s]year|desde|entre|respecto\s+(?:de|a)|comparado\s+con|"
    r"en\s+relaci[oó]n\s+(?:a|con)|interanual)\b",
    re.IGNORECASE,
)
_BASELINE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:baseline|per\s+capita|out\s+of|of\s+the\s+total|share\s+of|relative\s+to|"
    r"l[ií]nea\s+base|per\s+c[aá]pita|del\s+total|respecto\s+del\s+total|sobre\s+un\s+total)\b",
    re.IGNORECASE,
)
_FUTURE_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:will|shall|by\s+(?:19|20|21)\d{2}|next\s+year|in\s+the\s+coming|"
    r"se\s+espera|se\s+proyecta|hacia\s+(?:19|20|21)\d{2}|en\s+los\s+pr[oó]ximos)\b",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    """Lowercase and drop combining marks."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _content_words(text: str) -> frozenset[str]:
    """Return the meaning-bearing words of a passage, folded and de-stopped."""
    words = re.findall(r"[^\W\d_]{3,}", _fold(text), re.UNICODE)
    return frozenset(w for w in words if w not in _STOPWORDS)


def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
    """Share of the claim's content words that the passage also contains.

    Asymmetric on purpose: what matters is whether the evidence covers the claim,
    not whether the claim exhausts a long report.
    """
    if not a:
        return 0.0
    return len(a & b) / len(a)


# ---------------------------------------------------------------------------
# Evidence weighing
# ---------------------------------------------------------------------------


def evidential_weight(item: EvidenceItem, *, claim_words: frozenset[str]) -> float:
    """How much weight one item can bear on THIS claim, ignoring who published it.

    Four inputs, each defensible in the open:

    * the assessed strength of the item for its own question;
    * its relevance to the question, as recorded when it was collected;
    * whether it carries a quotable passage covering the claim's content — an
      item that cannot be pointed at must not move a verdict;
    * whether it is an independent observation or a restatement of one.

    Not an input: the publisher. Outlet standing carries no evidential weight
    anywhere in Aleph, and by the time an item reaches here the publisher has
    been pseudonymised out by :mod:`aleph.claims.blind` — so this function could
    not consult it even if it wanted to.
    """
    strength = _STRENGTH_WEIGHT.get(item.strength or EvidenceStrength.MEDIUM, 0.65)
    relevance = float(item.evidential_relevance.relevance)
    coverage = max(
        (_overlap(claim_words, _content_words(span.text)) for span in item.spans),
        default=0.0,
    )
    independence = 0.7 if (item.independence in _DEPENDENT_INDEPENDENCE) else 1.0
    if item.derived_from_evidence_id:
        independence = 0.6
    return round(strength * (0.35 + 0.4 * relevance + 0.25 * coverage) * independence, 4)


@dataclass(frozen=True)
class EvidenceView:
    """Everything the checks need from an evidence set, computed once.

    Built from a :class:`~aleph.core.models.RedactedClaimContext` and therefore
    identity-free by construction. Sharing it across the ten checks keeps them
    consistent with one another: two checks disagreeing about how many
    independent sources exist would make a verdict incoherent.
    """

    items: tuple[EvidenceItem, ...]
    claim_words: frozenset[str]
    numbers: tuple[tuple[str, ParsedNumber], ...]
    """``(evidence_id, number)`` pairs drawn from statements, spans and the
    structured quantity fields."""
    documentary_ids: tuple[str, ...]
    analytical_ids: tuple[str, ...]
    independent_source_ids: tuple[str, ...]
    weights: Mapping[str, float]
    coverage: Mapping[str, float]

    @property
    def count(self) -> int:
        """Number of evidence items shown to the evaluator."""
        return len(self.items)

    @property
    def independent_count(self) -> int:
        """Distinct independent originals. Ten copies of one report count once."""
        return len(self.independent_source_ids)

    def by_id(self, evidence_id: str) -> EvidenceItem | None:
        """Look up an item by its ``ev:`` id."""
        for item in self.items:
            if item.id == evidence_id:
                return item
        return None

    def covering(self, threshold: float = 0.45) -> tuple[EvidenceItem, ...]:
        """Items whose passages cover enough of the claim to speak to it."""
        return tuple(item for item in self.items if self.coverage.get(item.id, 0.0) >= threshold)


def _build_view(ctx: RedactedClaimContext) -> EvidenceView:
    """Index the evidence in a blind context for the ten checks."""
    claim_words = _content_words(ctx.claim_text)
    numbers: list[tuple[str, ParsedNumber]] = []
    documentary: list[str] = []
    analytical: list[str] = []
    independent: list[str] = []
    weights: dict[str, float] = {}
    coverage: dict[str, float] = {}

    for item in ctx.evidence:
        blob = " ".join([item.statement, *(span.text for span in item.spans)])
        for parsed in parse_numbers(blob):
            numbers.append((item.id, parsed))
        for quantity in item.quantities:
            numbers.extend((item.id, parsed) for parsed in parse_numbers(quantity.raw_text))
        if item.tier in DOCUMENTARY_TIERS:
            documentary.append(item.id)
        if item.tier in ANALYTICAL_TIERS:
            analytical.append(item.id)
        if (
            item.derived_from_evidence_id is None
            and item.independence not in _DEPENDENT_INDEPENDENCE
        ):
            independent.append(item.source_ref.id)
        weights[item.id] = evidential_weight(item, claim_words=claim_words)
        coverage[item.id] = max(
            (_overlap(claim_words, _content_words(span.text)) for span in item.spans),
            default=_overlap(claim_words, _content_words(item.statement)),
        )

    return EvidenceView(
        items=tuple(ctx.evidence),
        claim_words=claim_words,
        numbers=tuple(numbers),
        documentary_ids=tuple(dict.fromkeys(documentary)),
        analytical_ids=tuple(dict.fromkeys(analytical)),
        independent_source_ids=tuple(dict.fromkeys(independent)),
        weights=weights,
        coverage=coverage,
    )


# ---------------------------------------------------------------------------
# Quantitative re-checking
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QuantitativeFinding:
    """The result of re-doing a claim's arithmetic.

    ``declined`` is a first-class outcome, not a failure. A figure written with an
    ambiguous decimal separator cannot be checked without guessing a locale, and
    guessing would turn a transcription problem into a confident verdict about a
    speaker.
    """

    outcome: CheckOutcome
    notes: tuple[str, ...]
    matched: tuple[str, ...] = ()
    mismatched: tuple[str, ...] = ()
    declined: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


_FROM_TO_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:from|de)\s+(?P<a>[^,;]{1,45}?)\s+(?:to|a)\s+(?P<b>[^,;.]{1,45}?)(?=[\s,.;]|$)",
    re.IGNORECASE,
)
_CHANGE_WORD_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?P<word>increase|rise|rose|grew|growth|up|drop|fall|fell|decrease|decline|"
    r"reduction|cut|aumento|alza|incremento|subida|crecimiento|ca[ií]da|baja|"
    r"reducci[oó]n|descenso|disminuci[oó]n)\b",
    re.IGNORECASE,
)
_DOWNWARD: Final[frozenset[str]] = frozenset(
    {
        "drop",
        "fall",
        "fell",
        "decrease",
        "decline",
        "reduction",
        "cut",
        "caida",
        "caída",
        "baja",
        "reduccion",
        "reducción",
        "descenso",
        "disminucion",
        "disminución",
    }
)
_SHARE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<a>[\d.,]+)\s*(?:of|out\s+of|de\s+cada|de\s+los|de\s+las|de)\s+(?P<b>[\d.,]+)",
    re.IGNORECASE,
)


def _recheck_quantities(ctx: RedactedClaimContext, view: EvidenceView) -> QuantitativeFinding:
    """Re-do the claim's arithmetic against the evidence, and against itself.

    Two independent tests, both real computation rather than a judgement:

    **Internal consistency.** A claim of the form "from A to B, an increase of
    P%" contains its own proof. The percentage is recomputed from A and B and
    compared, and the *direction* is checked against the word used, because
    reporting a fall as a rise is a common and consequential error that a
    magnitude-only check would miss.

    **External agreement.** Each figure in the claim is matched against figures of
    the same kind found in the evidence, at :data:`NUMERIC_TOLERANCE`. Scale words
    are applied first, so "1.2 billion" and "1,200 million" compare equal instead
    of differing by a factor of a thousand.

    A claim whose figures are ambiguously punctuated is declined rather than
    guessed at, and a claim with no comparable evidence figures returns ``na`` —
    "we could not check this" is a different statement from "this is wrong", and
    Aleph must not merge them.
    """
    claim_numbers = parse_numbers(ctx.claim_text)
    if not claim_numbers:
        return QuantitativeFinding(
            outcome=CheckOutcome.NA,
            notes=("the claim asserts no figure, so there is no arithmetic to check",),
        )

    notes: list[str] = []
    matched: list[str] = []
    mismatched: list[str] = []
    declined: list[str] = []
    refs: list[str] = []

    # --- internal: recompute a stated percentage change -------------------
    from_to = _FROM_TO_RE.search(ctx.claim_text)
    percentages = [n for n in claim_numbers if n.kind.value == "percentage"]
    if from_to and percentages:
        a_numbers = parse_numbers(from_to.group("a"))
        b_numbers = parse_numbers(from_to.group("b"))
        if a_numbers and b_numbers:
            a = absolute_value(a_numbers[-1])
            b = absolute_value(b_numbers[0])
            stated = percentages[0].value
            if a == 0:
                declined.append("the stated base is zero, so a percentage change is undefined")
            elif a_numbers[-1].ambiguous_separator or b_numbers[0].ambiguous_separator:
                declined.append(
                    "the base or the endpoint uses an ambiguous decimal separator; "
                    "checking would require assuming a locale"
                )
            else:
                computed = (b - a) / a * 100.0
                word_match = _CHANGE_WORD_RE.search(ctx.claim_text)
                word = _fold(word_match.group("word")) if word_match else ""
                expected_down = word in _DOWNWARD
                size_ok = abs(abs(computed) - stated) <= max(PERCENT_POINT_TOLERANCE, 0.05 * stated)
                direction_ok = (computed < 0) == expected_down if word else True
                if size_ok and direction_ok:
                    matched.append(
                        f"stated change of {stated}% is consistent with {a:g} to {b:g} "
                        f"(recomputed {computed:.2f}%)"
                    )
                elif not direction_ok:
                    mismatched.append(
                        f"the claim describes a {'decrease' if expected_down else 'increase'} "
                        f"but {a:g} to {b:g} is a {computed:+.2f}% change"
                    )
                else:
                    mismatched.append(
                        f"stated change of {stated}% does not follow from {a:g} to {b:g}, "
                        f"which is {computed:.2f}%"
                    )

    # --- internal: recompute a stated share -------------------------------
    share = _SHARE_RE.search(ctx.claim_text)
    if share and percentages and not from_to:
        part_numbers = parse_numbers(share.group("a"))
        whole_numbers = parse_numbers(share.group("b"))
        if part_numbers and whole_numbers and absolute_value(whole_numbers[0]) != 0:
            part = absolute_value(part_numbers[0])
            whole = absolute_value(whole_numbers[0])
            computed = part / whole * 100.0
            stated = percentages[0].value
            if abs(computed - stated) <= max(PERCENT_POINT_TOLERANCE, 0.05 * stated):
                matched.append(
                    f"stated share of {stated}% is consistent with {part:g} of {whole:g} "
                    f"(recomputed {computed:.2f}%)"
                )
            else:
                mismatched.append(
                    f"stated share of {stated}% does not follow from {part:g} of {whole:g}, "
                    f"which is {computed:.2f}%"
                )

    # --- external: compare against figures in the evidence -----------------
    comparable = 0
    for number in claim_numbers:
        same_kind = [
            (evidence_id, other) for evidence_id, other in view.numbers if other.kind is number.kind
        ]
        if not same_kind:
            continue
        comparable += 1
        if number.ambiguous_separator:
            declined.append(
                f"{number.raw_text!r} uses an ambiguous decimal separator; the "
                "comparison would require assuming a locale"
            )
            continue
        target = absolute_value(number)
        hit = None
        for evidence_id, other in same_kind:
            if other.ambiguous_separator:
                continue
            value = absolute_value(other)
            scale = max(abs(target), abs(value), 1e-9)
            if abs(value - target) / scale <= NUMERIC_TOLERANCE:
                hit = evidence_id
                break
        if hit:
            matched.append(f"{number.raw_text!r} agrees with a figure in {hit}")
            refs.append(hit)
        else:
            nearest = min((abs(absolute_value(o) - target), eid, o) for eid, o in same_kind)
            mismatched.append(
                f"{number.raw_text!r} has no matching figure in the evidence; the "
                f"closest comparable value is {absolute_value(nearest[2]):g} in {nearest[1]}"
            )
            refs.append(nearest[1])

    if mismatched:
        outcome = CheckOutcome.FAIL
        notes.extend(mismatched)
        notes.extend(matched)
    elif matched:
        outcome = CheckOutcome.PASS
        notes.extend(matched)
    elif declined:
        outcome = CheckOutcome.NA
        notes.extend(declined)
    elif comparable == 0:
        outcome = CheckOutcome.NA
        notes.append(
            "the evidence contains no figure of the same kind, so the claim's "
            "arithmetic could not be checked against anything"
        )
    else:
        outcome = CheckOutcome.NA
        notes.append("no comparable figure could be resolved")
    notes.extend(declined if outcome is not CheckOutcome.NA else [])

    return QuantitativeFinding(
        outcome=outcome,
        notes=tuple(notes),
        matched=tuple(matched),
        mismatched=tuple(mismatched),
        declined=tuple(declined),
        evidence_refs=tuple(dict.fromkeys(refs)),
    )


# ---------------------------------------------------------------------------
# The ten checks
# ---------------------------------------------------------------------------


def _result(
    check: EpistemicCheck,
    outcome: CheckOutcome,
    note: str,
    refs: Iterable[str] = (),
) -> EpistemicCheckResult:
    """Build one recorded check result. ``note`` is never empty."""
    return EpistemicCheckResult(
        check=check,
        result=outcome,
        note=note,
        evidence_refs=list(dict.fromkeys(refs)),
    )


def _check_direct_textual_evidence(
    ctx: RedactedClaimContext, view: EvidenceView, cls: ClaimClassification
) -> EpistemicCheckResult:
    check = EpistemicCheck.DIRECT_TEXTUAL_EVIDENCE
    if cls.statement_type in {StatementType.OPINION, StatementType.NORMATIVE}:
        return _result(
            check,
            CheckOutcome.NA,
            "the statement expresses a preference or a duty; there is no passage that "
            "could confirm or deny it, and looking for one would manufacture a failure",
        )
    if view.count == 0:
        return _result(
            check,
            CheckOutcome.FAIL,
            "no evidence was placed before the evaluator, so no quotable passage "
            "supports the claim",
        )
    covering = view.covering()
    if covering:
        best = max(covering, key=lambda item: view.coverage[item.id])
        return _result(
            check,
            CheckOutcome.PASS,
            f"{len(covering)} item(s) carry a quotable passage covering the claim's "
            f"content; the closest ({best.id}) covers "
            f"{view.coverage[best.id]:.0%} of its content words",
            [item.id for item in covering],
        )
    best_id = max(view.coverage, key=lambda k: view.coverage[k], default=None)
    return _result(
        check,
        CheckOutcome.FAIL,
        "no evidence passage covers the claim's content closely enough to be quoted "
        "in support of it"
        + (
            f"; the nearest ({best_id}) reaches only {view.coverage[best_id]:.0%}"
            if best_id
            else ""
        ),
        [best_id] if best_id else [],
    )


def _check_data_consistency(
    ctx: RedactedClaimContext, view: EvidenceView, cls: ClaimClassification
) -> EpistemicCheckResult:
    check = EpistemicCheck.DATA_CONSISTENCY
    by_kind: dict[str, list[tuple[str, float]]] = {}
    for evidence_id, number in view.numbers:
        if number.ambiguous_separator:
            continue
        by_kind.setdefault(number.kind.value, []).append((evidence_id, absolute_value(number)))

    comparable = {
        kind: values
        for kind, values in by_kind.items()
        if len({evidence_id for evidence_id, _ in values}) >= 2
    }
    if not comparable:
        return _result(
            check,
            CheckOutcome.NA,
            "fewer than two independent items report a figure of the same kind, so "
            "there is nothing to compare",
        )
    conflicts: list[str] = []
    refs: list[str] = []
    for kind, values in comparable.items():
        lowest = min(values, key=lambda pair: pair[1])
        highest = max(values, key=lambda pair: pair[1])
        scale = max(abs(lowest[1]), abs(highest[1]), 1e-9)
        if (highest[1] - lowest[1]) / scale > NUMERIC_TOLERANCE * 4:
            conflicts.append(
                f"{kind} figures disagree: {lowest[1]:g} in {lowest[0]} against "
                f"{highest[1]:g} in {highest[0]}"
            )
            refs.extend([lowest[0], highest[0]])
    if conflicts:
        return _result(
            check,
            CheckOutcome.FAIL,
            "sources report incompatible figures, which the claim's verdict must not "
            "paper over: " + "; ".join(conflicts),
            refs,
        )
    return _result(
        check,
        CheckOutcome.PASS,
        f"figures of the same kind agree across {len(comparable)} measure(s) within "
        f"{NUMERIC_TOLERANCE * 400:.0f}% of one another",
        [evidence_id for values in comparable.values() for evidence_id, _ in values],
    )


def _check_quantitative_correctness(
    ctx: RedactedClaimContext, view: EvidenceView, cls: ClaimClassification
) -> EpistemicCheckResult:
    finding = _recheck_quantities(ctx, view)
    return _result(
        EpistemicCheck.QUANTITATIVE_CORRECTNESS,
        finding.outcome,
        "; ".join(finding.notes) or "no arithmetic to check",
        finding.evidence_refs,
    )


def _check_logical_validity(
    ctx: RedactedClaimContext, view: EvidenceView, cls: ClaimClassification
) -> EpistemicCheckResult:
    check = EpistemicCheck.LOGICAL_VALIDITY
    if cls.statement_type in {StatementType.OPINION, StatementType.NORMATIVE}:
        return _result(
            check,
            CheckOutcome.NA,
            "a preference or a duty has no premises to follow from; validity does not apply",
        )
    problems: list[str] = []
    if cls.asserts_universal and view.independent_count < 2:
        problems.append(
            "the claim is stated universally ('all', 'never', 'siempre'), which one "
            "counterexample refutes, but fewer than two independent sources are "
            "present to establish that no counterexample exists"
        )
    if _CONCLUSION_RE.search(ctx.claim_text) and view.count == 0:
        problems.append(
            "the claim draws a conclusion ('therefore', 'por lo tanto') from premises "
            "that were not supplied"
        )
    if cls.is_compound:
        problems.append(
            "the claim bundles more than one assertion, so a single verdict would be "
            "true of one part and false of another"
        )
    if problems:
        return _result(check, CheckOutcome.FAIL, "; ".join(problems))
    return _result(
        check,
        CheckOutcome.PASS,
        "the claim states a single assertion whose scope matches what the evidence "
        "before the evaluator can bear on",
    )


def _check_causal_support(
    ctx: RedactedClaimContext, view: EvidenceView, cls: ClaimClassification
) -> EpistemicCheckResult:
    check = EpistemicCheck.CAUSAL_SUPPORT
    if not cls.asserts_causation:
        return _result(
            check,
            CheckOutcome.NA,
            "the claim asserts no causal link, so there is no causal step to support",
        )
    mechanism_items = [
        item
        for item in view.items
        if _MECHANISM_RE.search(item.statement)
        or any(_MECHANISM_RE.search(span.text) for span in item.spans)
    ]
    if view.analytical_ids or mechanism_items:
        refs = list(view.analytical_ids) + [item.id for item in mechanism_items]
        return _result(
            check,
            CheckOutcome.PASS,
            "the evidence includes material carrying a method or a stated mechanism, "
            "so the causal step rests on more than sequence or correlation",
            refs,
        )
    return _result(
        check,
        CheckOutcome.FAIL,
        "the claim asserts causation but no evidence states a mechanism or carries an "
        "identification method; co-occurrence and sequence are not causal evidence",
    )


def _check_uncertainty_handling(
    ctx: RedactedClaimContext, view: EvidenceView, cls: ClaimClassification
) -> EpistemicCheckResult:
    check = EpistemicCheck.UNCERTAINTY_HANDLING
    forward = cls.statement_type is StatementType.FORECAST or bool(
        _FUTURE_MARKER_RE.search(ctx.claim_text)
    )
    if not forward:
        return _result(
            check,
            CheckOutcome.NA,
            "the claim makes no projection, so there are no assumptions or ranges it "
            "was obliged to state",
        )
    problems: list[str] = []
    if cls.asserts_certainty and not cls.explicit_assumptions() and not cls.is_hedged:
        problems.append(
            "a projection is asserted with certainty language and no stated assumption "
            "or range; the confidence expressed exceeds what a projection can carry"
        )
    if cls.statement_type is StatementType.FORECAST and not cls.is_falsifiable:
        problems.append(
            "the projection names neither a quantity nor a time frame, so no future "
            "observation could ever confirm or refute it"
        )
    if problems:
        return _result(check, CheckOutcome.FAIL, "; ".join(problems))
    stated = len(cls.explicit_assumptions())
    return _result(
        check,
        CheckOutcome.PASS,
        f"the projection is presented with {stated} stated assumption(s) and "
        f"{'hedged' if cls.is_hedged else 'unhedged but falsifiable'} language; its "
        f"{len(cls.assumptions)} recorded assumption(s) are published with the verdict",
    )


def _check_context_completeness(
    ctx: RedactedClaimContext, view: EvidenceView, cls: ClaimClassification
) -> EpistemicCheckResult:
    check = EpistemicCheck.CONTEXT_COMPLETENESS
    if not cls.is_quantitative:
        return _result(
            check,
            CheckOutcome.NA,
            "the claim carries no figure whose comparison class could have been omitted",
        )
    has_period = bool(_PERIOD_RE.search(ctx.claim_text))
    has_baseline = bool(_BASELINE_RE.search(ctx.claim_text))
    if has_period or has_baseline:
        return _result(
            check,
            CheckOutcome.PASS,
            "the claim names the period or the comparison class its figure is measured "
            "against, so the figure can be interpreted as stated",
        )
    supplying = [
        item.id
        for item in view.items
        if _PERIOD_RE.search(item.statement) or _BASELINE_RE.search(item.statement)
    ]
    if supplying:
        return _result(
            check,
            CheckOutcome.FAIL,
            "the claim states a figure without a period or comparison class, while the "
            "evidence does supply one; a bare figure invites the reader to assume the "
            "most favourable baseline",
            supplying,
        )
    return _result(
        check,
        CheckOutcome.PASS,
        "the claim states a figure without an explicit comparison class, and no "
        "evidence supplies one either, so nothing material was left out relative to "
        "what is known",
    )


def _check_temporal_correctness(
    ctx: RedactedClaimContext, view: EvidenceView, cls: ClaimClassification
) -> EpistemicCheckResult:
    check = EpistemicCheck.TEMPORAL_CORRECTNESS
    if ctx.made_at is None:
        return _result(
            check,
            CheckOutcome.NA,
            "the claim carries no date, so it cannot be judged against the state of the "
            "world at the time it was made",
        )
    if cls.statement_type is StatementType.FACT and _FUTURE_MARKER_RE.search(ctx.claim_text):
        return _result(
            check,
            CheckOutcome.FAIL,
            "the claim asserts a state of a period after the date it was made as though "
            "it were settled; a statement about the future is a projection and must be "
            "presented as one",
        )
    later = [
        item.id
        for item in view.items
        if item.source_ref.published_at and item.source_ref.published_at > ctx.made_at
    ]
    if later and len(later) == view.count:
        return _result(
            check,
            CheckOutcome.PASS,
            "every evidence item postdates the claim. Later evidence cannot make an "
            "earlier statement false at the time it was made, and this check records "
            "that so the verdict is about accuracy rather than hindsight",
            later,
        )
    return _result(
        check,
        CheckOutcome.PASS,
        "the claim's date and the evidence's dates are consistent with one another; "
        "nothing in the record places the claim outside the period it describes",
        [item.id for item in view.items],
    )


def _check_independent_corroboration(
    ctx: RedactedClaimContext, view: EvidenceView, cls: ClaimClassification
) -> EpistemicCheckResult:
    check = EpistemicCheck.INDEPENDENT_CORROBORATION
    if cls.statement_type in {StatementType.OPINION, StatementType.NORMATIVE}:
        return _result(
            check,
            CheckOutcome.NA,
            "a preference is not corroborated by repetition; the check does not apply",
        )
    count = view.independent_count
    if count >= 2:
        return _result(
            check,
            CheckOutcome.PASS,
            f"{count} genuinely independent originals bear on the claim, out of "
            f"{view.count} item(s) shown",
            [item.id for item in view.items],
        )
    return _result(
        check,
        CheckOutcome.FAIL,
        f"only {count} independent original(s) bear on the claim; restatements of one "
        "source are one piece of evidence, however many items carry them",
        [item.id for item in view.items],
    )


def _conflicting_items(
    ctx: RedactedClaimContext, view: EvidenceView
) -> list[tuple[EvidenceItem, str]]:
    """Find evidence that says the opposite, blind to who published it.

    Two blind-safe signals, both textual or numeric:

    * **polarity** — the item covers the claim's content but carries a negation
      the claim does not (or the reverse);
    * **magnitude** — the item reports a figure of the same kind that differs by
      more than tolerance while covering the same content.

    The evidence graph's own ``contradicts`` links are deliberately not used
    here: they point at claim ids, and the blind context carries no claim id
    precisely so that nothing about which claim this is can reach the evaluator.
    """
    claim_negated = bool(_NEGATION_RE.search(ctx.claim_text))
    claim_numbers = parse_numbers(ctx.claim_text)
    out: list[tuple[EvidenceItem, str]] = []
    for item in view.items:
        if view.coverage.get(item.id, 0.0) < 0.35:
            continue
        blob = " ".join([item.statement, *(span.text for span in item.spans)])
        if bool(_NEGATION_RE.search(blob)) != claim_negated:
            out.append(
                (
                    item,
                    "the item covers the same content with the opposite polarity",
                )
            )
            continue
        for number in claim_numbers:
            if number.ambiguous_separator:
                continue
            same_kind = [
                other
                for other in parse_numbers(blob)
                if other.kind is number.kind and not other.ambiguous_separator
            ]
            if not same_kind:
                continue
            target = absolute_value(number)
            if all(
                abs(absolute_value(other) - target) / max(abs(target), 1e-9) > NUMERIC_TOLERANCE * 4
                for other in same_kind
            ):
                out.append(
                    (
                        item,
                        f"the item reports {absolute_value(same_kind[0]):g} where the "
                        f"claim asserts {target:g}",
                    )
                )
                break
    return out


def _check_contradiction(
    ctx: RedactedClaimContext, view: EvidenceView, cls: ClaimClassification
) -> EpistemicCheckResult:
    check = EpistemicCheck.CONTRADICTION_WITH_STRONGER_EVIDENCE
    if view.count == 0:
        return _result(
            check,
            CheckOutcome.NA,
            "no evidence was shown, so nothing could contradict the claim",
        )
    conflicts = _conflicting_items(ctx, view)
    if not conflicts:
        return _result(
            check,
            CheckOutcome.PASS,
            "no item before the evaluator asserts the opposite of the claim",
            [item.id for item in view.items],
        )
    conflict_weight = max(view.weights.get(item.id, 0.0) for item, _ in conflicts)
    conflict_ids = {item.id for item, _ in conflicts}
    supporting = [item for item in view.items if item.id not in conflict_ids]
    support_weight = max((view.weights.get(item.id, 0.0) for item in supporting), default=0.0)
    reasons = "; ".join(reason for _, reason in conflicts)
    if conflict_weight > support_weight:
        return _result(
            check,
            CheckOutcome.FAIL,
            "evidence carrying more weight for this question says otherwise "
            f"({conflict_weight:.2f} against {support_weight:.2f}, computed from "
            f"assessed strength, relevance, passage coverage and independence, and "
            f"from nothing about who published it): {reasons}",
            sorted(conflict_ids),
        )
    return _result(
        check,
        CheckOutcome.PASS,
        "some evidence disagrees, but it does not carry more weight for this question "
        f"({conflict_weight:.2f} against {support_weight:.2f}): {reasons}",
        sorted(conflict_ids),
    )


_CHECK_FUNCTIONS: Final[
    Mapping[
        EpistemicCheck,
        Any,
    ]
] = {
    EpistemicCheck.DIRECT_TEXTUAL_EVIDENCE: _check_direct_textual_evidence,
    EpistemicCheck.DATA_CONSISTENCY: _check_data_consistency,
    EpistemicCheck.QUANTITATIVE_CORRECTNESS: _check_quantitative_correctness,
    EpistemicCheck.LOGICAL_VALIDITY: _check_logical_validity,
    EpistemicCheck.CAUSAL_SUPPORT: _check_causal_support,
    EpistemicCheck.UNCERTAINTY_HANDLING: _check_uncertainty_handling,
    EpistemicCheck.CONTEXT_COMPLETENESS: _check_context_completeness,
    EpistemicCheck.TEMPORAL_CORRECTNESS: _check_temporal_correctness,
    EpistemicCheck.INDEPENDENT_CORROBORATION: _check_independent_corroboration,
    EpistemicCheck.CONTRADICTION_WITH_STRONGER_EVIDENCE: _check_contradiction,
}


def run_checks(
    ctx: RedactedClaimContext,
    *,
    classification: ClaimClassification | None = None,
    view: EvidenceView | None = None,
) -> tuple[EpistemicCheckResult, ...]:
    """Run all ten epistemic checks, always all ten, always in canonical order.

    A check that does not apply returns ``na`` with a reason rather than being
    omitted. That distinction is the point: a reader must be able to tell "this
    was tested and passed" from "this does not apply here" from "this was never
    looked at", and a list that silently omits the third case makes every verdict
    look more thoroughly tested than it was.
    """
    cls = classification or classify_claim_text(ctx.claim_text)
    evidence_view = view or _build_view(ctx)
    return tuple(_CHECK_FUNCTIONS[check](ctx, evidence_view, cls) for check in EPISTEMIC_CHECKS)


# ---------------------------------------------------------------------------
# The decision function
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerdictDerivation:
    """A verdict, the named rule that produced it, and the reasoning to publish.

    The rule name is exported so that a bundle can be audited in aggregate: if
    most ``unsupported`` verdicts in a corpus come from a single rule, that rule
    deserves scrutiny, and no amount of per-claim prose would have made the
    pattern visible.
    """

    verdict: Verdict
    rule: str
    reasoning: str
    failed_core: tuple[EpistemicCheck, ...] = ()
    failed_supporting: tuple[EpistemicCheck, ...] = ()
    applicable: tuple[EpistemicCheck, ...] = ()


def derive_verdict(
    checks: Sequence[EpistemicCheckResult],
    classification: ClaimClassification,
    *,
    evidence_count: int,
) -> VerdictDerivation:
    """Turn ten recorded check results into one verdict, by explicit rules.

    This function is deliberately ordinary code. No model is asked for a label at
    any point, because a label from a model cannot be argued with: it arrives
    whole, it cannot be reproduced, and a reader who disagrees has nowhere to put
    the disagreement. Here every verdict names the rule that produced it and the
    checks that fired, so disagreement lands on a specific step.

    The rules, in the order they are tried:

    1. ``non_factual_statement_type`` — an opinion or a normative claim is
       ``not_a_factual_claim``. Never ``unsupported``, which would read as a
       refutation of something never offered as a finding.
    2. ``forecast_never_graded`` — a forecast is ``forecast_conditional`` and
       carries its assumptions. A projection marked ``supported`` would tell a
       reader the future had been checked.
    3. ``stronger_evidence_contradicts`` — ``contradicted``.
    4. ``no_evidence`` / ``nothing_applicable`` — ``unverifiable``. Absence of
       evidence is a fact about the evidence base, not about the claim.
    5. ``untestable_on_this_evidence`` — nothing quotable and nothing
       corroborating, and no arithmetic failure to bite on: ``unverifiable``
       rather than ``unsupported``.
    6. ``core_checks_failed`` — an arithmetic failure, or two or more core
       failures: ``unsupported``.
    7. ``single_core_failure`` / ``supporting_checks_failed`` —
       ``partially_supported``.
    8. ``all_applicable_checks_passed`` — ``supported``.
    """
    outcomes = {result.check: result.result for result in checks}
    notes = {result.check: (result.note or "") for result in checks}
    applicable = tuple(
        check for check, outcome in outcomes.items() if outcome is not CheckOutcome.NA
    )
    failed_core = tuple(
        check
        for check in CORE_CHECKS
        if outcomes.get(check) is CheckOutcome.FAIL
        and check is not EpistemicCheck.CONTRADICTION_WITH_STRONGER_EVIDENCE
    )
    failed_supporting = tuple(
        check for check in SUPPORTING_CHECKS if outcomes.get(check) is CheckOutcome.FAIL
    )
    passed = tuple(check for check, outcome in outcomes.items() if outcome is CheckOutcome.PASS)

    def finish(verdict: Verdict, rule: str, head: str) -> VerdictDerivation:
        lines = [head]
        for check in failed_core + failed_supporting:
            lines.append(f"FAILED {check.value}: {notes.get(check, '')}")
        for check in passed:
            lines.append(f"passed {check.value}: {notes.get(check, '')}")
        lines.append(
            f"Rule applied: {rule}. {len(applicable)} of the ten checks applied to a "
            f"statement of type '{classification.statement_type.value}'; "
            f"{len(passed)} passed, {len(failed_core) + len(failed_supporting)} failed, "
            f"{10 - len(applicable)} did not apply."
        )
        return VerdictDerivation(
            verdict=verdict,
            rule=rule,
            reasoning=" ".join(lines),
            failed_core=failed_core,
            failed_supporting=failed_supporting,
            applicable=applicable,
        )

    if classification.statement_type in {StatementType.OPINION, StatementType.NORMATIVE}:
        return finish(
            Verdict.NOT_A_FACTUAL_CLAIM,
            "non_factual_statement_type",
            "The statement expresses a preference or asserts what ought to be done. It "
            "is not the kind of thing that can be true or false, so it is recorded as "
            "not a factual claim rather than graded against evidence.",
        )

    if classification.statement_type is StatementType.FORECAST:
        return finish(
            Verdict.FORECAST_CONDITIONAL,
            "forecast_never_graded",
            "The statement is a projection about the future. It is evaluable only "
            "against the assumptions it depends on, which are published with this "
            "verdict, and it is never marked supported: a projection that has not "
            "happened yet cannot have been verified.",
        )

    if outcomes.get(EpistemicCheck.CONTRADICTION_WITH_STRONGER_EVIDENCE) is CheckOutcome.FAIL:
        return finish(
            Verdict.CONTRADICTED,
            "stronger_evidence_contradicts",
            "Evidence carrying more weight for this question asserts the opposite.",
        )

    if evidence_count == 0:
        return finish(
            Verdict.UNVERIFIABLE,
            "no_evidence",
            "No evidence was placed before the evaluator. That is a fact about the "
            "evidence base, not about the claim, and it is published as such rather "
            "than converted into a judgement.",
        )

    if not applicable:
        return finish(
            Verdict.UNVERIFIABLE,
            "nothing_applicable",
            "None of the ten checks could be applied to this statement on the evidence available.",
        )

    quant = outcomes.get(EpistemicCheck.QUANTITATIVE_CORRECTNESS)
    untestable = (
        outcomes.get(EpistemicCheck.DIRECT_TEXTUAL_EVIDENCE) is CheckOutcome.FAIL
        and outcomes.get(EpistemicCheck.INDEPENDENT_CORROBORATION) is not CheckOutcome.PASS
        and quant is not CheckOutcome.FAIL
    )
    if untestable:
        return finish(
            Verdict.UNVERIFIABLE,
            "untestable_on_this_evidence",
            "Nothing in the evidence quotes or corroborates the claim, and no "
            "arithmetic error was found either. Aleph cannot say the claim is wrong; "
            "it can only say it could not be checked on what was collected.",
        )

    if quant is CheckOutcome.FAIL or len(failed_core) >= 2:
        return finish(
            Verdict.UNSUPPORTED,
            "core_checks_failed",
            "The claim fails checks that go to its substance: the evidence does not "
            "support what it asserts.",
        )

    if failed_core:
        return finish(
            Verdict.PARTIALLY_SUPPORTED,
            "single_core_failure",
            "Part of the claim holds against the evidence and part does not.",
        )

    if failed_supporting:
        return finish(
            Verdict.PARTIALLY_SUPPORTED,
            "supporting_checks_failed",
            "The substance of the claim survives every check that attacks it, but it "
            "falls short on corroboration, context or the handling of uncertainty — "
            "which qualifies it without refuting it.",
        )

    return finish(
        Verdict.SUPPORTED,
        "all_applicable_checks_passed",
        "Every check that applies to this statement passed on the evidence shown.",
    )


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def compute_evidence_confidence(
    checks: Sequence[EpistemicCheckResult],
    view: EvidenceView,
    classification: ClaimClassification,
) -> Confidence:
    """Compute confidence from the evidence, and only from the evidence.

    This function never reads a model's self-report. It cannot: no provider is
    passed to it. That is deliberate — the failure this whole product exists to
    prevent is a confident answer resting on nothing, and the surest way to
    produce one is to let a model's disposition set the headline number.

    Every factor moves the figure by a stated amount and is recorded in
    :attr:`~aleph.core.models.Confidence.basis` with its direction, so a reader
    who thinks corroboration should count for more than quantitative validation
    can see exactly where to argue. ``limiting_factor`` names the single largest
    drag in plain words, because "0.42" tells a reader nothing they can act on
    and "no independent corroboration" tells them what to go and find.

    A hard ceiling applies on top: confidence cannot exceed what the sheer volume
    of independent evidence can bear, however many checks happened to pass.
    """
    outcomes = {result.check: result.result for result in checks}
    basis: list[ConfidenceBasis] = []
    contributions: list[tuple[str, float]] = []
    score = 0.35

    def record(factor: ConfidenceFactor, delta: float, note: str, label: str | None = None) -> None:
        nonlocal score
        score += delta
        contributions.append((label or factor.value, delta))
        basis.append(
            ConfidenceBasis(
                factor=factor,
                effect=(
                    ConfidenceEffect.RAISES
                    if delta > 0
                    else ConfidenceEffect.LOWERS
                    if delta < 0
                    else ConfidenceEffect.NEUTRAL
                ),
                note=note,
            )
        )

    documentary_share = (len(view.documentary_ids) / view.count) if view.count else 0.0
    record(
        ConfidenceFactor.PRIMARY_SOURCE_COVERAGE,
        0.20 * documentary_share - (0.12 if documentary_share == 0 else 0.0),
        f"{len(view.documentary_ids)} of {view.count} item(s) are primary documents, "
        "legislative records, official technical reports or statistical datasets — "
        "the kinds of artefact that can establish what a text or a dataset says",
    )

    agreement = outcomes.get(EpistemicCheck.DATA_CONSISTENCY)
    record(
        ConfidenceFactor.EVIDENCE_AGREEMENT,
        0.12
        if agreement is CheckOutcome.PASS
        else (-0.20 if agreement is CheckOutcome.FAIL else 0.0),
        {
            CheckOutcome.PASS: "figures of the same kind agree across sources",
            CheckOutcome.FAIL: "sources report incompatible figures, which no verdict may paper over",
            CheckOutcome.NA: "too few comparable figures to test agreement",
        }[agreement or CheckOutcome.NA],
    )

    quant = outcomes.get(EpistemicCheck.QUANTITATIVE_CORRECTNESS)
    record(
        ConfidenceFactor.QUANTITATIVE_VALIDATION,
        0.15 if quant is CheckOutcome.PASS else (-0.25 if quant is CheckOutcome.FAIL else 0.0),
        {
            CheckOutcome.PASS: "the claim's arithmetic was re-derived and holds",
            CheckOutcome.FAIL: "the claim's arithmetic does not hold when re-derived",
            CheckOutcome.NA: "no figure could be independently re-derived",
        }[quant or CheckOutcome.NA],
    )

    independent = view.independent_count
    record(
        ConfidenceFactor.SOURCE_INDEPENDENCE,
        {0: -0.15, 1: -0.05}.get(independent, 0.10 if independent == 2 else 0.15),
        f"{independent} genuinely independent original(s); restatements of one source "
        "are counted once, because repetition is not corroboration",
    )

    temporal = outcomes.get(EpistemicCheck.TEMPORAL_CORRECTNESS)
    record(
        ConfidenceFactor.TEMPORAL_CONSISTENCY,
        0.08
        if temporal is CheckOutcome.PASS
        else (-0.15 if temporal is CheckOutcome.FAIL else -0.04),
        {
            CheckOutcome.PASS: "the claim's date sits consistently with the evidence's dates",
            CheckOutcome.FAIL: "the claim asserts a future period as settled fact",
            CheckOutcome.NA: "the claim carries no date, so it cannot be placed in time",
        }[temporal or CheckOutcome.NA],
    )

    record(
        ConfidenceFactor.RETRIEVAL_COMPLETENESS,
        {0: -0.30, 1: -0.10, 2: 0.0}.get(view.count, 0.08),
        f"{view.count} evidence item(s) were collected for this claim",
    )

    ambiguity = 0.0
    ambiguity_notes: list[str] = []
    if classification.margin < 0.5:
        ambiguity -= 0.08
        ambiguity_notes.append(
            f"the statement-type classification won by only {classification.margin:.2f}, "
            "so the sentence carried mixed signals"
        )
    if classification.is_compound:
        ambiguity -= 0.08
        ambiguity_notes.append("the claim bundles more than one assertion")
    record(
        ConfidenceFactor.CLAIM_AMBIGUITY,
        ambiguity,
        "; ".join(ambiguity_notes)
        or "the claim reads as a single assertion of an unambiguous type",
    )

    # Ceiling: however many checks passed, confidence cannot outrun the volume of
    # independent evidence behind it. Four independent originals is the point at
    # which the ceiling stops binding.
    ceiling = 0.35 + 0.15 * min(independent, 4)
    if view.count == 0:
        ceiling = 0.10
    score = max(0.02, min(score, ceiling, 0.97))

    worst = min(contributions, key=lambda pair: pair[1], default=("none", 0.0))
    limiting = None
    if worst[1] < 0:
        limiting = next(
            (entry.note for entry in basis if entry.factor.value == worst[0] and entry.note),
            worst[0].replace("_", " "),
        )
    elif score < ceiling + 1e-9 and view.count:
        limiting = (
            f"confidence is capped by the volume of independent evidence: "
            f"{independent} independent original(s) support a ceiling of {ceiling:.2f}"
        )

    return Confidence(
        evidence_confidence=round(score, 3),
        model_confidence=None,
        basis=basis,
        limiting_factor=limiting,
    )


_SELF_REPORT_PROMPT = """\
TASK: evaluator_self_report

A claim has already been evaluated against evidence by an explicit rule engine.
Report only your own confidence in that reading, as JSON with a `model_confidence`
float in [0,1] and a short `note`. This figure is recorded as a diagnostic and is
never used to set the published confidence.

CLAIM: {claim}
VERDICT: {verdict}
EVIDENCE ITEMS: {count}
"""


def _model_self_report(
    provider: ClaimLLMProvider | None, ctx: RedactedClaimContext, verdict: Verdict
) -> float | None:
    """Ask a provider what it thinks, and record it as a diagnostic.

    Deliberately isolated in its own function that returns a bare float, so that
    the value has exactly one destination — ``Confidence.model_confidence`` — and
    could not be threaded into :func:`compute_evidence_confidence` without an
    obvious edit. A provider failure returns ``None``, which is the honest value
    and never an obstacle: the verdict was produced without the model.
    """
    if provider is None:
        return None
    prompt = _SELF_REPORT_PROMPT.format(
        claim=ctx.claim_text, verdict=verdict.value, count=len(ctx.evidence)
    )
    try:
        raw = provider.complete(prompt, schema={"type": "object"})
        payload = json.loads(raw)
        value = float(payload["model_confidence"])
    except Exception:  # noqa: BLE001 - a diagnostic must never break an evaluation
        return None
    return round(min(1.0, max(0.0, value)), 3)


# ---------------------------------------------------------------------------
# Stage one
# ---------------------------------------------------------------------------


def _uncertainties(
    checks: Sequence[EpistemicCheckResult],
    view: EvidenceView,
    classification: ClaimClassification,
) -> list[Uncertainty]:
    """Publish what remains unresolved, with what would settle it."""
    outcomes = {result.check: result.result for result in checks}
    out: list[Uncertainty] = []
    if view.count == 0:
        out.append(
            Uncertainty(
                statement="No evidence was collected for this claim.",
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by="any primary document or dataset bearing on the assertion",
            )
        )
    if view.independent_count < 2:
        out.append(
            Uncertainty(
                statement=("Fewer than two genuinely independent originals bear on this claim."),
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by="a second source that is not a restatement of the first",
            )
        )
    if outcomes.get(EpistemicCheck.DATA_CONSISTENCY) is CheckOutcome.FAIL:
        out.append(
            Uncertainty(
                statement="Sources report incompatible figures for the same measure.",
                kind=UncertaintyKind.CONFLICTING_EVIDENCE,
                resolvable_by="the underlying dataset, or a statement of the definitions each source used",
            )
        )
    if outcomes.get(EpistemicCheck.QUANTITATIVE_CORRECTNESS) is CheckOutcome.NA and (
        classification.is_quantitative
    ):
        out.append(
            Uncertainty(
                statement=(
                    "The claim states a figure that no collected evidence could be "
                    "compared against."
                ),
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by="the source of the figure, or any dataset reporting the same measure",
            )
        )
    if classification.margin < 0.5:
        out.append(
            Uncertainty(
                statement=(
                    "The statement carries mixed linguistic signals, so its type — and "
                    "therefore which checks apply — is not certain."
                ),
                kind=UncertaintyKind.DEFINITIONAL_AMBIGUITY,
                resolvable_by="a clearer restatement of the assertion by its source",
            )
        )
    if classification.statement_type is StatementType.FORECAST:
        out.append(
            Uncertainty(
                statement=(
                    "This is a projection. It can be evaluated only against the "
                    "assumptions listed with this verdict, and only once the period it "
                    "describes has passed."
                ),
                kind=UncertaintyKind.TEMPORAL,
                resolvable_by="outturn data for the period the projection covers",
            )
        )
    return out


def evaluate_blind(
    ctx: RedactedClaimContext,
    provider: ClaimLLMProvider | None = None,
) -> BlindEvaluation:
    """Stage one. Produce a verdict from the redacted context and nothing else.

    The signature is the guarantee: there is no ``claim`` parameter, no
    ``speaker`` parameter and no way to pass provenance. Whatever this function
    concludes, it concluded without knowing who was talking — and
    :meth:`~aleph.core.models.RedactedClaimContext.to_redacted_context` records
    exactly what it was shown, so a sceptical reader can verify that rather than
    take it on faith.

    ``provider`` is optional and is used for one thing only: a self-reported
    confidence stored in ``model_confidence`` as a diagnostic. It plays no part in
    the checks, no part in the verdict and no part in evidence confidence. With
    no provider the field is ``None``, and the evaluation is otherwise identical.

    Args:
        ctx: The blind context. The only input to the factual judgement.
        provider: Optional model, for the diagnostic self-report.

    Returns:
        A :class:`~aleph.core.models.BlindEvaluation`, which is the only object in
        Aleph where a verdict may be written.
    """
    ctx = assert_blind_input(ctx)
    classification = classify_claim_text(ctx.claim_text)
    view = _build_view(ctx)
    checks = run_checks(ctx, classification=classification, view=view)
    derivation = derive_verdict(checks, classification, evidence_count=view.count)
    confidence = compute_evidence_confidence(checks, view, classification)

    model_confidence = _model_self_report(provider, ctx, derivation.verdict)
    if model_confidence is not None:
        confidence = confidence.model_copy(update={"model_confidence": model_confidence})

    refs: list[str] = []
    for result in checks:
        if result.result is not CheckOutcome.NA:
            refs.extend(result.evidence_refs)

    assumptions: list[str] = []
    if derivation.verdict is Verdict.FORECAST_CONDITIONAL:
        assumptions = classification.assumption_statements()

    return BlindEvaluation(
        evaluator_version=EVALUATOR_VERSION,
        redacted_context=ctx.to_redacted_context(),
        verdict=derivation.verdict,
        reasoning=derivation.reasoning,
        evidence_refs=list(dict.fromkeys(refs)),
        assumptions_required=assumptions,
        confidence=confidence,
        uncertainties=_uncertainties(checks, view, classification),
    )


# ---------------------------------------------------------------------------
# Stage two
# ---------------------------------------------------------------------------

#: Cues for the named rhetorical patterns. Recorded only after a verdict exists,
#: and never treated as evidence about truth: a claim delivered with urgency
#: framing may be entirely accurate, and a claim delivered plainly may be false.
RHETORIC_CUES: Final[Mapping[RhetoricalPattern, re.Pattern[str]]] = {
    RhetoricalPattern.APPEAL_TO_AUTHORITY: re.compile(
        r"\b(?:as\s+the\s+\w+\s+(?:said|says)|any\s+expert|experts\s+agree|"
        r"como\s+dijo\s+el|los\s+expertos\s+coinciden|nadie\s+discute)\b",
        re.IGNORECASE,
    ),
    RhetoricalPattern.FALSE_DILEMMA: re.compile(
        r"\b(?:either\s+.{3,40}\s+or\b|the\s+only\s+(?:option|alternative|way)|"
        r"o\s+bien\s+.{3,40}\s+o\b|la\s+[uú]nica\s+(?:opci[oó]n|alternativa|salida))\b",
        re.IGNORECASE,
    ),
    RhetoricalPattern.ANECDOTE_AS_EVIDENCE: re.compile(
        r"\b(?:i\s+(?:know|met)\s+(?:someone|a\s+\w+)|a\s+family\s+(?:i|we)\s+met|"
        r"conoc[ií]\s+a|un\s+caso\s+que|me\s+cont[oó])\b",
        re.IGNORECASE,
    ),
    RhetoricalPattern.URGENCY_FRAMING: re.compile(
        r"\b(?:crisis|emergency|immediately|before\s+it\s+is\s+too\s+late|urgent(?:ly)?|"
        r"emergencia|urgente|de\s+inmediato|colapso|antes\s+de\s+que\s+sea\s+tarde)\b",
        re.IGNORECASE,
    ),
    RhetoricalPattern.MORAL_FRAMING: re.compile(
        r"\b(?:immoral|shameful|betrayal|duty|obscene|unconscionable|"
        r"inmoral|vergonzoso|traici[oó]n|deber\s+moral|indecente|injusto)\b",
        re.IGNORECASE,
    ),
    RhetoricalPattern.LOADED_COMPARISON: re.compile(
        r"\b(?:worse\s+than|nothing\s+short\s+of|akin\s+to|tantamount\s+to|"
        r"peor\s+que|equivalente\s+a\s+un|no\s+es\s+m[aá]s\s+que)\b",
        re.IGNORECASE,
    ),
}

_JARGON_RE: Final[re.Pattern[str]] = re.compile(r"\b[^\W\d_]{13,}\b", re.UNICODE)


def _rhetorical_observations(
    text: str, classification: ClaimClassification
) -> list[RhetoricalObservation]:
    """Name the patterns present in how a claim was expressed.

    Naming a pattern is not a refutation and must never be presented as one. The
    observations exist so a reader can separate an argument from its packaging;
    the verdict was already fixed before this function ran.
    """
    out: list[RhetoricalObservation] = []
    for pattern, regex in RHETORIC_CUES.items():
        match = regex.search(text)
        if match:
            out.append(
                RhetoricalObservation(
                    pattern=pattern,
                    span=None,
                    note=f"matched {match.group(0).strip()!r}",
                )
            )
    if (
        classification.statement_type is StatementType.FORECAST
        and not classification.is_falsifiable
    ):
        out.append(
            RhetoricalObservation(
                pattern=RhetoricalPattern.UNFALSIFIABLE_PREDICTION,
                span=None,
                note=(
                    "the projection names neither a quantity nor a time frame, so no "
                    "outcome could ever settle it"
                ),
            )
        )
    if (
        classification.is_quantitative
        and not _PERIOD_RE.search(text)
        and not _BASELINE_RE.search(text)
    ):
        out.append(
            RhetoricalObservation(
                pattern=RhetoricalPattern.CHERRY_PICKED_STATISTIC,
                span=None,
                note=(
                    "a figure is cited without the period or comparison class it is "
                    "measured against, which leaves the reader to supply the most "
                    "favourable one"
                ),
            )
        )
    words = text.split()
    if words and len(_JARGON_RE.findall(text)) / len(words) > 0.25:
        out.append(
            RhetoricalObservation(
                pattern=RhetoricalPattern.TECHNICAL_OBFUSCATION,
                span=None,
                note="unusually high density of long technical terms for a public statement",
            )
        )
    if not out:
        out.append(
            RhetoricalObservation(
                pattern=RhetoricalPattern.NONE_DETECTED,
                span=None,
                note="no named rhetorical pattern was detected in how the claim was expressed",
            )
        )
    return out


def _framing_notes(claim: Any, classification: ClaimClassification) -> list[str]:
    """Describe how the claim was packaged, without re-judging whether it is true."""
    notes: list[str] = []
    form = getattr(getattr(claim, "form", None), "value", None)
    if form == "direct_quotation":
        notes.append(
            "Presented as a direct quotation, so the wording is the speaker's own and "
            "the outlet's framing is confined to what it chose to quote."
        )
    elif form == "indirect_quotation":
        notes.append(
            "Presented as reported speech, so the wording is the reporter's; the "
            "verbatim sentence is retained beside the claim for comparison."
        )
    elif form == "assertion":
        notes.append(
            "Stated in the outlet's own voice with no attribution, which makes it a "
            "claim by the publication rather than a report of someone else's claim."
        )
    if classification.asserts_certainty:
        notes.append(
            "Delivered with certainty language "
            f"({', '.join(h.matched_text for h in classification.cues_for('certainty'))}), "
            "which is a property of the delivery and not of the evidence."
        )
    if classification.asserts_causation:
        notes.append(
            "Frames the relationship as causal rather than as an association, which "
            "raises what the claim would need to establish."
        )
    if classification.is_quantitative:
        notes.append(
            "Leads with a figure; which figure is chosen from those available is itself "
            "an editorial decision."
        )
    if classification.statement_type is StatementType.FORECAST:
        stated = len(classification.explicit_assumptions())
        notes.append(
            f"A projection presented with {stated} stated assumption(s); "
            f"{len(classification.assumptions) - stated} further assumption(s) are "
            "implied by the form of the projection and were not stated."
        )
    return notes


def _historical_consistency(claim: Any, prior_claims: Sequence[Any]) -> HistoricalConsistency:
    """Compare a claim with the same actor's earlier statements.

    Descriptive context only. An actor who changed position may have changed it
    because the evidence changed, so an inconsistency recorded here never touches
    a verdict — and this function has no access to one.
    """
    speaker = getattr(getattr(claim, "provenance", None), "speaker_name", None)
    role = getattr(getattr(claim, "provenance", None), "speaker_role", None)
    if not speaker and not role:
        return HistoricalConsistency(
            assessment=HistoricalConsistencyAssessment.NOT_ASSESSED,
            prior_claim_refs=[],
            note="the statement carries no attribution, so there is no history to compare it with",
        )
    same_actor = [
        prior
        for prior in prior_claims
        if getattr(getattr(prior, "provenance", None), "speaker_name", None) == speaker
        and speaker is not None
    ]
    if not same_actor:
        return HistoricalConsistency(
            assessment=HistoricalConsistencyAssessment.INSUFFICIENT_HISTORY,
            prior_claim_refs=[],
            note="no earlier statement by the same actor is present in this corpus",
        )
    current = _content_words(getattr(claim, "normalised_text", ""))
    contradicting: list[str] = []
    shifted: list[str] = []
    for prior in same_actor:
        prior_text = getattr(prior, "normalised_text", "")
        if _overlap(current, _content_words(prior_text)) < 0.4:
            continue
        prior_negated = bool(_NEGATION_RE.search(prior_text))
        now_negated = bool(_NEGATION_RE.search(getattr(claim, "normalised_text", "")))
        target = contradicting if prior_negated != now_negated else shifted
        target.append(getattr(prior, "id", ""))
    if contradicting:
        return HistoricalConsistency(
            assessment=HistoricalConsistencyAssessment.CONTRADICTS_PRIOR,
            prior_claim_refs=[ref for ref in contradicting if ref],
            note=(
                "an earlier statement by the same actor asserts the opposite on the same "
                "subject. This is context for a reader, not a truth test: a position "
                "changed because the evidence changed is not an error"
            ),
        )
    if shifted:
        return HistoricalConsistency(
            assessment=HistoricalConsistencyAssessment.CONSISTENT,
            prior_claim_refs=[ref for ref in shifted if ref],
            note="earlier statements by the same actor address the same subject compatibly",
        )
    return HistoricalConsistency(
        assessment=HistoricalConsistencyAssessment.INSUFFICIENT_HISTORY,
        prior_claim_refs=[],
        note="earlier statements exist but none addresses the same subject closely enough to compare",
    )


def assert_verdict_preserved(before: BlindEvaluation, after: BlindEvaluation) -> None:
    """Raise unless the blind evaluation is byte-for-byte what it was.

    The runtime proof of Aleph's central claim. Stage two knows who spoke; if
    knowing that changed anything about the factual judgement — the verdict, the
    reasoning, the confidence, the evidence it rested on — then the two-stage
    separation failed and the result must not be published.

    Comparison is over the whole serialised object rather than the verdict alone,
    because a stage that left the label alone while nudging confidence from 0.8 to
    0.4 would have done exactly the thing this design forbids.

    Raises:
        NeutralityViolationError: If anything about the blind evaluation moved.
    """
    before_blob = json.dumps(before.to_jsonable(), sort_keys=True, ensure_ascii=False)
    after_blob = json.dumps(after.to_jsonable(), sort_keys=True, ensure_ascii=False)
    if before_blob == after_blob:
        return
    raise NeutralityViolationError(
        "the attributed stage altered the blind evaluation; a factual verdict must be "
        "structurally unable to change once the speaker is known, so this is a defect "
        "in Aleph and the result must not be published",
        perturbation="attributed_stage_guard",
        original_verdict=before.verdict.value,
        perturbed_verdict=after.verdict.value,
        confidence_delta=round(
            after.confidence.evidence_confidence - before.confidence.evidence_confidence, 6
        ),
    )


def analyse_attributed(
    claim: ExtractedClaim | Claim | Any,
    blind_result: BlindEvaluation,
    *,
    prior_claims: Sequence[Any] = (),
    classification: ClaimClassification | None = None,
    analyser_version: str = ATTRIBUTION_ANALYSER_VERSION,
) -> AttributedAnalysis:
    """Stage two. Restore provenance and describe how the claim was made.

    Structurally unable to alter the verdict, in three independent ways:

    1. ``blind_result`` is *input*, and the return type is a different class.
       :class:`~aleph.core.models.AttributedAnalysis` has no verdict, confidence,
       override or adjustment field, so there is nowhere to write one.
    2. The evaluation is deep-copied before any of this runs, and
       :func:`assert_verdict_preserved` compares the caller's object against that
       snapshot on the way out. Mutating it — deliberately or by accident —
       raises.
    3. ``applied_after_verdict`` is pinned to ``True`` by the model itself, so a
       record asserting that attribution came first cannot be constructed.

    What this stage *is* for: framing (what was foregrounded, which figure was
    chosen), historical consistency, and named rhetorical patterns. All of it is
    context a reader deserves, and none of it bears on whether the claim is true.

    ``speaker_role`` is populated only with a functional role. Where extraction
    recovered a personal name but no role, the name goes to ``speaker_id`` as an
    ``actor:`` identifier and the role field stays ``None``, matching Aleph's rule
    that a role, not a private individual, is what gets published.

    Raises:
        NeutralityViolationError: If the blind evaluation changed during this call.
    """
    snapshot = blind_result.model_copy(deep=True)

    provenance = getattr(claim, "provenance", None)
    speaker_name = getattr(provenance, "speaker_name", None)
    speaker_role = getattr(provenance, "speaker_role", None)
    outlet_id = getattr(provenance, "outlet_id", None)

    cls = classification or getattr(claim, "classification", None)
    if cls is None:
        cls = classify_claim_text(getattr(claim, "normalised_text", "") or "")

    text = getattr(claim, "text", None) or getattr(claim, "normalised_text", "") or ""

    speaker_id: str | None = None
    if speaker_name:
        try:
            speaker_id = make_actor_id(slugify(speaker_name))
        except ValueError:
            speaker_id = None

    analysis = AttributedAnalysis(
        applied_after_verdict=True,
        speaker_role=speaker_role,
        speaker_id=speaker_id,
        outlet_id=outlet_id if isinstance(outlet_id, str) and ":" in outlet_id else None,
        framing_notes=[
            *_framing_notes(claim, cls),
            f"Attributed analysis produced by {analyser_version}, after the blind "
            f"verdict '{blind_result.verdict.value}' was recorded.",
        ],
        historical_consistency=_historical_consistency(claim, prior_claims),
        rhetorical_pattern=_rhetorical_observations(text, cls),
    )

    assert_verdict_preserved(snapshot, blind_result)
    return analysis


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimEvaluation:
    """A fully evaluated claim, with everything needed to audit how it got there."""

    claim: Claim
    blinding: Blinding
    checks: tuple[EpistemicCheckResult, ...]
    derivation: VerdictDerivation
    view: EvidenceView

    @property
    def verdict(self) -> Verdict:
        """The verdict, read from the only place one may be written."""
        return self.claim.blind_evaluation.verdict

    def as_dict(self) -> dict[str, Any]:
        """Render the claim and its audit trail as JSON-safe mappings."""
        return {
            "claim": self.claim.to_jsonable(),
            "blinding": self.blinding.as_dict(),
            "verdict_rule": self.derivation.rule,
            "evidence_items": self.view.count,
            "independent_sources": self.view.independent_count,
        }


def build_claim(
    extracted: ExtractedClaim,
    blind_result: BlindEvaluation,
    attributed: AttributedAnalysis | None,
    checks: Sequence[EpistemicCheckResult],
) -> Claim:
    """Assemble the published :class:`~aleph.core.models.Claim` record.

    Note the shape the contract enforces and this function respects: there is no
    top-level verdict. The verdict lives inside ``blind_evaluation`` and nowhere
    else, so the attributed analysis sits beside it with nothing to overwrite.
    """
    return Claim(
        id=extracted.id,
        text=extracted.text,
        normalised_text=extracted.normalised_text,
        statement_type=extracted.statement_type,
        made_at=extracted.made_at,
        provenance=extracted.provenance.to_model(),
        quantities=list(extracted.quantities),
        money=list(extracted.money),
        blind_evaluation=blind_result,
        attributed_analysis=attributed,
        checks_applied=list(checks),
        article_id=extracted.provenance.article_id,
    )


def evaluate_claim(
    extracted: ExtractedClaim,
    evidence: Sequence[EvidenceItem] = (),
    *,
    vocabulary: IdentityVocabulary | None = None,
    provider: ClaimLLMProvider | None = None,
    prior_claims: Sequence[Any] = (),
    policy: RedactionPolicy | None = None,
    run_attributed: bool = True,
) -> ClaimEvaluation:
    """Run the whole pipeline for one claim: blind, evaluate, then attribute.

    The order is the design. Redaction happens first and its result is verified;
    the verdict is produced from the redacted context alone; only then is
    provenance restored, and the guard confirms the verdict did not move. A
    caller cannot invert this — there is no argument that would let attribution
    run first, and the blind context is the only thing :func:`evaluate_blind`
    accepts.

    Args:
        extracted: The claim, with its identity compartment intact.
        evidence: Items to place before the evaluator.
        vocabulary: Identities to strip. Defaults to the ones this claim's own
            provenance names, which is the minimum; a corpus-wide vocabulary from
            :func:`~aleph.claims.extract.merge_vocabularies` is better.
        provider: Optional model, used only for the diagnostic self-report.
        prior_claims: Earlier claims, for the historical-consistency observation.
        policy: Redaction policy.
        run_attributed: Set ``False`` to publish the blind result alone. The
            record then carries ``attributed_analysis: null``, which is an honest
            statement that stage two has not run — not a missing field.

    Returns:
        A :class:`ClaimEvaluation` holding the published claim and its audit trail.
    """
    vocab = vocabulary or IdentityVocabulary.build(persons=extracted.identities())
    blinding = blind_claim(
        extracted,
        evidence,
        vocabulary=vocab,
        context_excerpts=extracted.context_excerpts,
        policy=policy,
        claim_id=extracted.id,
    )
    ctx = blinding.context
    classification = classify_claim_text(ctx.claim_text)
    view = _build_view(ctx)
    checks = run_checks(ctx, classification=classification, view=view)
    derivation = derive_verdict(checks, classification, evidence_count=view.count)
    blind_result = evaluate_blind(ctx, provider)

    attributed = (
        analyse_attributed(extracted, blind_result, prior_claims=prior_claims)
        if run_attributed
        else None
    )
    claim = build_claim(extracted, blind_result, attributed, checks)
    return ClaimEvaluation(
        claim=claim,
        blinding=blinding,
        checks=checks,
        derivation=derivation,
        view=view,
    )


@dataclass(frozen=True)
class EvaluationBatch:
    """Several evaluated claims, with the distribution of verdicts.

    ``verdict_counts`` is worth reading before any single verdict: a claim set
    that is mostly ``unverifiable`` is telling a reader about the state of the
    evidence base, not about the honesty of anyone in it.
    """

    evaluations: tuple[ClaimEvaluation, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def verdict_counts(self) -> dict[str, int]:
        """How many claims received each verdict."""
        counts = {verdict.value: 0 for verdict in Verdict}
        for evaluation in self.evaluations:
            counts[evaluation.verdict.value] += 1
        return counts

    @property
    def all_blind_clean(self) -> bool:
        """True when no evaluation's blind context leaked an identity."""
        return all(e.blinding.leaks.clean for e in self.evaluations)


def evaluate_all(
    claims: Iterable[ExtractedClaim],
    evidence_for: Mapping[str, Sequence[EvidenceItem]] | None = None,
    *,
    vocabulary: IdentityVocabulary | None = None,
    provider: ClaimLLMProvider | None = None,
    policy: RedactionPolicy | None = None,
) -> EvaluationBatch:
    """Evaluate a set of claims, feeding each one its own evidence.

    Earlier claims are passed forward as history for later ones, so
    historical-consistency observations accumulate across a corpus without any
    caller having to thread them manually.
    """
    ordered = list(claims)
    lookup = evidence_for or {}
    out: list[ClaimEvaluation] = []
    seen: list[ExtractedClaim] = []
    for claim in ordered:
        out.append(
            evaluate_claim(
                claim,
                lookup.get(claim.id, ()),
                vocabulary=vocabulary,
                provider=provider,
                prior_claims=tuple(seen),
                policy=policy,
            )
        )
        seen.append(claim)
    return EvaluationBatch(evaluations=tuple(out))
