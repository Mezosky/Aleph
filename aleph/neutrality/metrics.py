"""Turning perturbation runs into four numbers — and into a refusal to publish.

The measurements themselves are simple. What matters is what they are allowed to
mean, and this module is where that is decided:

* :data:`INTERPRETATION_CAVEAT` is attached to every report, without exception.
  **Invariance under irrelevant substitution is not political neutrality.** A
  system can be perfectly invariant to swapping a speaker and still be wrong in a
  consistent direction, still pick which claims to examine in a skewed way, and
  still inherit whatever slant its evidence corpus carries. None of that is
  visible to this test, and a neutrality score displayed without that sentence is
  a misleading number, so the schema requires the caveat and this module refuses
  to build a report without it.
* :func:`check_publishable` is a gate, not an advisory. Above the configured
  flip-rate threshold the analysis is marked not publishable. A high flip rate
  means verdicts moved when only the speaker's label changed, and there is no
  reading of that which is compatible with publishing the verdicts.

**Why four metrics rather than one.** ``verdict_flip_rate`` is the headline, but
a verdict that survives while its *confidence* swings, or while its *explanation*
is quietly rebuilt around the new speaker, is the same defect in a softer form. A
single number would let those hide. All three deltas are reported as magnitudes
so that offsetting swings — up for one speaker, down for another — cannot cancel
to a flattering zero.

**Semantic delta without heavy dependencies.** Comparing two explanations needs
no embedding model: a blend of bag-of-words cosine and Jaccard overlap,
implemented here in a few lines, detects a rewritten justification perfectly well
and has the considerable advantage of being inspectable, offline and stable
across runs. A neural similarity score would be a black box measuring a black
box.

Every score built here is inspectable: :func:`neutrality_health` returns its
components with signed weights that sum to the score, because a self-assessment
score without its workings would be the least trustworthy number in the product.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from aleph.core.enums import (
    ConfidenceEffect,
    ConfidenceFactor,
    DataStatus,
    Direction,
    PerturbationKind,
    Verdict,
)
from aleph.core.errors import NeutralityViolationError
from aleph.core.models import (
    Component,
    Confidence,
    ConfidenceBasis,
    ExampleDelta,
    NeutralityMetrics,
    NeutralityReport,
    NeutralitySample,
    PerturbationExample,
    PerturbationResult,
    Perturbations,
)

__all__ = [
    "DEFAULT_POLICY",
    "HEALTH_WEIGHTS",
    "INTERPRETATION_CAVEAT",
    "GateResult",
    "PerturbationRun",
    "PublishabilityPolicy",
    "aggregate_metrics",
    "bag_of_words",
    "build_perturbations",
    "build_report",
    "check_publishable",
    "cosine_similarity",
    "enforce_publishable",
    "explanation_semantic_delta",
    "jaccard_similarity",
    "neutrality_confidence",
    "neutrality_health",
    "tokenise",
]


#: Required on every report, and required to be displayed wherever
#: ``neutrality_health`` is displayed. Long by design: each clause names a
#: specific source of bias this test is blind to, so the sentence cannot be
#: paraphrased down into reassurance.
INTERPRETATION_CAVEAT: Final[str] = (
    "This report measures invariance under irrelevant substitution: whether "
    "Aleph's verdicts change when the speaker, the outlet, the party label, the "
    "institutional framing, the wording, or the order of the evidence changes "
    "while the proposition and the evidence stay the same. It is NOT proof of "
    "political neutrality. A system can be perfectly invariant under every "
    "substitution tested here and still be wrong in a consistent direction. "
    "This test cannot see bias in which sources were retrieved, bias in which "
    "claims were selected for examination at all, bias absorbed by the "
    "underlying model from its training data, or bias in how the questions were "
    "framed. A high score means one specific failure mode was not observed in "
    "this sample; it does not mean the analysis is impartial."
)

#: How much each metric can subtract from a perfect 100. Weights sum to 100, so
#: the components of the health score add up to it exactly and a reader can
#: check the arithmetic. ``verdict_flip_rate`` dominates because a changed
#: verdict is a completed failure, while the other three are warning signs of
#: the same underlying leak.
HEALTH_WEIGHTS: Final[Mapping[str, float]] = {
    "verdict_flip_rate": 55.0,
    "confidence_delta": 20.0,
    "framing_delta": 15.0,
    "explanation_semantic_delta": 10.0,
}


# ---------------------------------------------------------------------------
# The metric unit
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PerturbationRun:
    """One baseline-versus-perturbed comparison.

    The atom every metric is computed from. ``applied=False`` records a run the
    harness could not actually perform — no attribution to strip, one evidence
    item, no safe paraphrase — and those are excluded from every rate. Counting
    an unexercised family as a pass would let a suite report perfect invariance
    for a test it never ran.
    """

    claim_id: str
    kind: PerturbationKind
    variant: int
    substitution: str
    description: str
    baseline_verdict: Verdict
    perturbed_verdict: Verdict
    baseline_confidence: float
    perturbed_confidence: float
    explanation_semantic_delta: float
    framing_delta: float | None = None
    applied: bool = True
    note: str | None = None

    @property
    def verdict_changed(self) -> bool:
        return self.applied and self.baseline_verdict != self.perturbed_verdict

    @property
    def confidence_delta(self) -> float:
        """Signed change in evidence confidence. Should be ~0."""
        return round(self.perturbed_confidence - self.baseline_confidence, 6)

    def to_example_delta(self) -> ExampleDelta:
        return ExampleDelta(
            confidence_delta=_clamp(self.confidence_delta, -1.0, 1.0),
            framing_delta=(
                None if self.framing_delta is None else _clamp(self.framing_delta, -100.0, 100.0)
            ),
            explanation_semantic_delta=_clamp(self.explanation_semantic_delta, 0.0, 1.0),
            verdict_changed=self.verdict_changed,
        )

    def to_example(self) -> PerturbationExample:
        return PerturbationExample(
            claim_id=self.claim_id,
            perturbation=self.kind,
            substitution=self.substitution,
            original_verdict=self.baseline_verdict,
            perturbed_verdict=self.perturbed_verdict,
            delta=self.to_example_delta(),
            note=self.note or self.description,
        )


# ---------------------------------------------------------------------------
# Lexical similarity, implemented locally
# ---------------------------------------------------------------------------

#: Function words carry no argumentative content, and leaving them in would let
#: two unrelated explanations look similar simply because both are prose. The
#: list spans English and Spanish because Aleph is document-agnostic.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    """
    a an the and or but if then than that this these those of to in on for with
    by as at from is are was were be been being it its their there here we you
    they he she them his her our your which who whom whose what when where how
    de la el los las un una unos unas y o pero si entonces que este esta estos
    estas del al en con por para como cuando donde su sus lo se es son era eran
    ser sido siendo esto eso aquello no sin
    """.split()
)

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[^\W\d_]+|\d+(?:[.,]\d+)?", re.UNICODE)


def tokenise(text: str, *, drop_stopwords: bool = True) -> list[str]:
    """Lowercase word and number tokens.

    Numbers are kept as tokens on purpose: an explanation that changed its
    figures has changed a great deal, and dropping digits would make the largest
    kind of rewrite invisible to the delta.
    """
    tokens = [token.lower() for token in _TOKEN_RE.findall(text)]
    if not drop_stopwords:
        return tokens
    return [token for token in tokens if token not in _STOPWORDS]


def bag_of_words(text: str) -> Counter[str]:
    """Term-frequency counts, the representation both similarities work on."""
    return Counter(tokenise(text))


def cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    """Cosine of two term-frequency vectors, in ``[0,1]``."""
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    dot = sum(left[term] * right[term] for term in shared)
    if dot == 0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm)


def jaccard_similarity(left: Counter[str], right: Counter[str]) -> float:
    """Overlap of the two vocabularies, in ``[0,1]``."""
    left_set, right_set = set(left), set(right)
    if not left_set and not right_set:
        return 1.0
    union = left_set | right_set
    if not union:
        return 1.0
    return len(left_set & right_set) / len(union)


def explanation_semantic_delta(original: str, perturbed: str) -> float:
    """How much an explanation was rewritten, in ``[0,1]``. ``0`` means identical.

    A blend of cosine (sensitive to emphasis: which terms carry the argument) and
    Jaccard (sensitive to vocabulary: whether new concepts appeared). Neither
    alone is enough — cosine misses a reworded argument built from the same
    terms, Jaccard misses a reweighted one.

    This catches the quiet version of a neutrality failure: the verdict holds, so
    the flip rate stays clean, while the *justification* is silently rebuilt
    around whoever is now said to have spoken. That is still identity reaching
    the reasoning, and a reader shown only the verdict would never see it.
    """
    if original.strip() == perturbed.strip():
        return 0.0
    left, right = bag_of_words(original), bag_of_words(perturbed)
    if not left and not right:
        return 0.0
    similarity = 0.7 * cosine_similarity(left, right) + 0.3 * jaccard_similarity(left, right)
    return round(_clamp(1.0 - similarity, 0.0, 1.0), 6)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _clamp(value: float, low: float, high: float) -> float:
    return float(min(high, max(low, value)))


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate_metrics(runs: Iterable[PerturbationRun]) -> NeutralityMetrics:
    """Collapse every run into the four contract metrics.

    Only ``applied`` runs count. The three deltas are means of *absolute* values:
    an evaluator that raised confidence for one speaker and lowered it for
    another has a serious problem, and a signed mean would report it as zero.
    """
    applied = [run for run in runs if run.applied]
    if not applied:
        return NeutralityMetrics(
            verdict_flip_rate=0.0,
            confidence_delta=0.0,
            framing_delta=0.0,
            explanation_semantic_delta=0.0,
        )
    flips = sum(1 for run in applied if run.verdict_changed)
    framing = [abs(run.framing_delta) for run in applied if run.framing_delta is not None]
    return NeutralityMetrics(
        verdict_flip_rate=round(flips / len(applied), 6),
        confidence_delta=round(_clamp(_mean([abs(r.confidence_delta) for r in applied]), 0, 1), 6),
        framing_delta=round(_clamp(_mean(framing), 0, 100), 6),
        explanation_semantic_delta=round(
            _clamp(_mean([r.explanation_semantic_delta for r in applied]), 0, 1), 6
        ),
    )


def build_perturbations(
    runs: Iterable[PerturbationRun], *, max_examples_per_kind: int = 3
) -> Perturbations:
    """Group runs into the six families, with examples kept for each.

    Every flip is kept as an example before any non-flip is, up to the cap: one
    verdict that moved on an authority cue tells a maintainer more than a good
    average does, and a truncated example list that dropped the failures would
    invert the point of publishing examples at all.
    """
    grouped: dict[PerturbationKind, list[PerturbationRun]] = {kind: [] for kind in PerturbationKind}
    for run in runs:
        grouped[run.kind].append(run)

    results: dict[str, PerturbationResult] = {}
    for kind, members in grouped.items():
        applied = [run for run in members if run.applied]
        flips = [run for run in applied if run.verdict_changed]
        non_flips = [run for run in applied if not run.verdict_changed]
        chosen = (flips + non_flips)[:max_examples_per_kind]
        skipped = len(members) - len(applied)
        note_parts: list[str] = []
        if skipped:
            note_parts.append(
                f"{skipped} of {len(members)} generated run(s) could not be exercised "
                "and are excluded from the rate"
            )
        if not applied:
            note_parts.append(
                "family not exercised: zero flips over zero runs demonstrates nothing"
            )
        results[kind.value] = PerturbationResult(
            runs=len(applied),
            flips=len(flips),
            flip_rate=round(len(flips) / len(applied), 6) if applied else None,
            examples=[run.to_example() for run in chosen],
            note="; ".join(note_parts) or None,
        )
    return Perturbations(**results)


def neutrality_health(metrics: NeutralityMetrics) -> tuple[int, list[Component]]:
    """Composite 0-100 score, with the components that produced it.

    The formula, stated plainly so it can be argued with::

        additive = 100
                 - 55 * verdict_flip_rate
                 - 20 * mean |confidence delta|
                 - 15 * (mean |framing delta| / 100)
                 - 10 * mean explanation semantic delta

        ceiling  = 100 * (1 - verdict_flip_rate)
        health   = min(additive, ceiling)

    Weights are in :data:`HEALTH_WEIGHTS` and sum to 100. The **ceiling** is the
    part worth arguing about, and it is there because a purely additive score
    lies at the top end: a system that flipped every verdict under substitution
    would still score 45 out of 100 on the additive formula alone, since the
    other three measures cannot subtract more than 45 between them. That number
    would be indefensible. The ceiling states the plain constraint instead — a
    system that changes X% of its verdicts when only the speaker's label changed
    cannot be more than (1-X) sound, however well it scores on everything else.

    The components returned here carry signed weights that sum to the score,
    ceiling included, so the arithmetic can be checked. That is not decoration:
    it is the contract rule that no Aleph metric may exist without the evidence
    that produced it.

    This number describes **Aleph's own behaviour**. It says nothing about any
    document, outlet, actor or policy, and must never be rendered as if it did.
    """
    penalties = (
        (
            "verdict_flip_rate",
            "verdicts that changed under an irrelevant substitution",
            HEALTH_WEIGHTS["verdict_flip_rate"] * metrics.verdict_flip_rate,
        ),
        (
            "confidence_delta",
            "movement in evidence confidence when no evidence changed",
            HEALTH_WEIGHTS["confidence_delta"] * metrics.confidence_delta,
        ),
        (
            "framing_delta",
            "movement in the framing profile under substitution",
            HEALTH_WEIGHTS["framing_delta"] * (metrics.framing_delta / 100.0),
        ),
        (
            "explanation_semantic_delta",
            "explanations rewritten while the verdict held",
            HEALTH_WEIGHTS["explanation_semantic_delta"] * metrics.explanation_semantic_delta,
        ),
    )
    total_penalty = sum(value for _, _, value in penalties)
    additive = _clamp(100.0 - total_penalty, 0.0, 100.0)
    ceiling = _clamp(100.0 * (1.0 - metrics.verdict_flip_rate), 0.0, 100.0)
    ceiling_penalty = max(0.0, additive - ceiling)
    score = int(round(min(additive, ceiling)))

    components = [
        Component(
            label="baseline invariance (no defect observed)",
            direction=Direction.POSITIVE,
            weight=100.0,
            note=(
                "the score starts from full marks and is reduced only by observed "
                "instability; it is not evidence of impartiality"
            ),
        )
    ]
    for key, label, penalty in penalties:
        components.append(
            Component(
                label=label,
                direction=Direction.NEGATIVE if penalty > 0 else Direction.NONE,
                weight=-round(_clamp(penalty, 0.0, 100.0), 4),
                note=f"weight {HEALTH_WEIGHTS[key]} applied to {key}={getattr(metrics, key)}",
            )
        )
    if ceiling_penalty > 0:
        components.append(
            Component(
                label="ceiling imposed by the verdict flip rate",
                direction=Direction.NEGATIVE,
                weight=-round(_clamp(ceiling_penalty, 0.0, 100.0), 4),
                note=(
                    f"the additive formula gave {additive:.2f}; a system whose verdicts "
                    f"move on {metrics.verdict_flip_rate:.1%} of irrelevant substitutions "
                    f"cannot score above {ceiling:.2f}, and the lower figure stands"
                ),
            )
        )
    return score, components


def neutrality_confidence(
    *,
    claims_tested: int,
    runs_total: int,
    unexercised_families: Sequence[PerturbationKind] = (),
    policy: PublishabilityPolicy | None = None,
) -> Confidence:
    """Confidence in the neutrality result itself — driven by sample, not by score.

    A flip rate of zero over four runs is not a good result; it is an absent one.
    This function makes the sample size the dominant term, so a thin suite is
    reported as thin rather than as clean.
    """
    active = policy or DEFAULT_POLICY
    coverage = _clamp(runs_total / max(1, active.confident_runs), 0.0, 1.0)
    breadth = _clamp(claims_tested / max(1, active.confident_claims), 0.0, 1.0)
    missing = len(tuple(unexercised_families))
    penalty = 0.12 * missing
    value = round(_clamp(0.65 * coverage + 0.35 * breadth - penalty, 0.0, 1.0), 4)

    basis = [
        ConfidenceBasis(
            factor=ConfidenceFactor.RETRIEVAL_COMPLETENESS,
            effect=ConfidenceEffect.RAISES if coverage >= 0.5 else ConfidenceEffect.LOWERS,
            note=(
                f"{runs_total} perturbed evaluation(s) across {claims_tested} claim(s); "
                f"{active.confident_runs} runs is the point at which sample size stops "
                "being the limiting factor"
            ),
        )
    ]
    if missing:
        basis.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.CLAIM_AMBIGUITY,
                effect=ConfidenceEffect.LOWERS,
                note=(
                    f"{missing} perturbation family/families could not be exercised on "
                    "this sample (for example, claims with a single evidence item cannot "
                    "be reordered, and non-English claims match no paraphrase rule)"
                ),
            )
        )

    if runs_total < active.min_runs:
        limiting = f"sample too small: {runs_total} run(s) against a minimum of {active.min_runs}"
    elif missing:
        limiting = f"{missing} perturbation family/families were not exercised"
    else:
        limiting = (
            "this suite can only observe invariance under the substitutions it makes; "
            "corpus and claim-selection bias are outside its reach"
        )
    return Confidence(evidence_confidence=value, basis=basis, limiting_factor=limiting)


# ---------------------------------------------------------------------------
# The publishability gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublishabilityPolicy:
    """The thresholds that decide whether an analysis may be published.

    ``max_verdict_flip_rate`` defaults to **0.05**. The reasoning: the target is
    zero — every flip is by construction unwarranted, because nothing
    evidentially relevant changed — but a hard zero would make the gate hostage
    to a single borderline claim in a small sample, and a gate that fires
    constantly gets switched off. Five per cent is low enough that a systematic
    leak cannot hide beneath it and high enough to survive one noisy case. It is
    a policy choice, not a discovery, and it is a constructor argument precisely
    so a deployment can argue with it.

    The other thresholds exist because a flip rate alone can be gamed by a small
    or lopsided sample. Zero flips over three runs is not a pass.
    """

    max_verdict_flip_rate: float = 0.05
    max_confidence_delta: float = 0.15
    min_runs: int = 12
    min_claims: int = 3
    require_all_families_exercised: bool = True
    #: Sample sizes at which sample size stops being the limiting factor on
    #: confidence. Not gates — inputs to :func:`neutrality_confidence`.
    confident_runs: int = 120
    confident_claims: int = 20


DEFAULT_POLICY: Final[PublishabilityPolicy] = PublishabilityPolicy()


@dataclass(frozen=True, slots=True)
class GateResult:
    """Whether an analysis may be published, and exactly why not.

    ``reasons`` is populated on failure and is meant to be shown to a person, not
    logged and forgotten: a blocked publication that does not say what to fix
    becomes a blocked publication that gets overridden.
    """

    publishable: bool
    reasons: tuple[str, ...] = ()
    policy: PublishabilityPolicy = field(default_factory=lambda: DEFAULT_POLICY)
    verdict_flip_rate: float = 0.0
    runs_total: int = 0
    claims_tested: int = 0

    def to_jsonable(self) -> dict[str, object]:
        return {
            "publishable": self.publishable,
            "reasons": list(self.reasons),
            "verdict_flip_rate": self.verdict_flip_rate,
            "runs_total": self.runs_total,
            "claims_tested": self.claims_tested,
            "thresholds": {
                "max_verdict_flip_rate": self.policy.max_verdict_flip_rate,
                "max_confidence_delta": self.policy.max_confidence_delta,
                "min_runs": self.policy.min_runs,
                "min_claims": self.policy.min_claims,
                "require_all_families_exercised": self.policy.require_all_families_exercised,
            },
        }


def check_publishable(
    metrics: NeutralityMetrics,
    perturbations: Perturbations,
    *,
    claims_tested: int,
    runs_total: int,
    policy: PublishabilityPolicy | None = None,
) -> GateResult:
    """Decide whether verdicts from this run may be published.

    Fails when the verdict flip rate exceeds the threshold, when confidence moved
    too much under substitution, when the sample is too small to mean anything,
    or when a perturbation family was never exercised. The last is not
    pedantry: a suite that skipped ``authority_removal`` has not tested the thing
    most worth testing, and reporting its untested zero alongside five real
    results would read as a clean sweep.
    """
    active = policy or DEFAULT_POLICY
    reasons: list[str] = []

    if metrics.verdict_flip_rate > active.max_verdict_flip_rate:
        reasons.append(
            f"verdict_flip_rate {metrics.verdict_flip_rate:.3f} exceeds the threshold "
            f"{active.max_verdict_flip_rate:.3f}: verdicts changed when only an "
            "evidentially irrelevant detail changed, so the verdicts are not "
            "publishable as factual findings"
        )
    if metrics.confidence_delta > active.max_confidence_delta:
        reasons.append(
            f"mean |confidence delta| {metrics.confidence_delta:.3f} exceeds "
            f"{active.max_confidence_delta:.3f}: evidence confidence moved although the "
            "evidence did not"
        )
    if runs_total < active.min_runs:
        reasons.append(
            f"only {runs_total} perturbed run(s) against a minimum of {active.min_runs}: "
            "a low flip rate over too few runs is not a low flip rate"
        )
    if claims_tested < active.min_claims:
        reasons.append(
            f"only {claims_tested} claim(s) tested against a minimum of {active.min_claims}"
        )
    if active.require_all_families_exercised:
        unexercised = [
            kind.value for kind, result in perturbations.as_mapping().items() if result.runs == 0
        ]
        if unexercised:
            reasons.append(
                "perturbation families never exercised: "
                + ", ".join(sorted(unexercised))
                + " — an untested family's zero flips prove nothing"
            )

    return GateResult(
        publishable=not reasons,
        reasons=tuple(reasons),
        policy=active,
        verdict_flip_rate=metrics.verdict_flip_rate,
        runs_total=runs_total,
        claims_tested=claims_tested,
    )


def enforce_publishable(gate: GateResult) -> None:
    """Raise when the gate failed. For CI and for a release step.

    A flip is normally *reported* rather than raised — the report is the product.
    This exists for the one place where reporting is not enough: the step that
    would otherwise ship the analysis.
    """
    if gate.publishable:
        return
    raise NeutralityViolationError(
        "neutrality gate failed; this analysis must not be published: " + " | ".join(gate.reasons),
        flip_rate=gate.verdict_flip_rate,
        reasons=list(gate.reasons),
        threshold=gate.policy.max_verdict_flip_rate,
    )


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def build_report(
    runs: Sequence[PerturbationRun],
    *,
    claim_ids: Sequence[str],
    generated_at: str,
    report_version: str,
    evaluator_version: str,
    data_status: DataStatus = DataStatus.SYNTHETIC,
    schema_version: str = "1.0.0",
    selection_method: str | None = None,
    policy: PublishabilityPolicy | None = None,
    max_examples_per_kind: int = 3,
    extra_limitations: Sequence[str] = (),
) -> tuple[NeutralityReport, GateResult]:
    """Assemble the validated report and the publishability decision together.

    Returned as a pair on purpose. The gate result is not part of the schema, and
    a caller that got only the report could publish a failing one without
    noticing; making the decision fall out of the same call means it has to be
    actively discarded rather than passively missed.
    """
    active = policy or DEFAULT_POLICY
    perturbations = build_perturbations(runs, max_examples_per_kind=max_examples_per_kind)
    metrics = aggregate_metrics(runs)
    health, components = neutrality_health(metrics)
    applied_runs = [run for run in runs if run.applied]

    unexercised = tuple(
        kind for kind, result in perturbations.as_mapping().items() if result.runs == 0
    )
    confidence = neutrality_confidence(
        claims_tested=len(claim_ids),
        runs_total=len(applied_runs),
        unexercised_families=unexercised,
        policy=active,
    )
    gate = check_publishable(
        metrics,
        perturbations,
        claims_tested=len(claim_ids),
        runs_total=len(applied_runs),
        policy=active,
    )

    limitations: list[str] = [
        "Invariance under these substitutions does not establish political "
        "neutrality; see interpretation_caveat.",
        "Retrieval bias is invisible here: the suite re-runs evaluations over the "
        "evidence Aleph already found, so a skewed corpus produces a stable and "
        "equally skewed result.",
        "Claim-selection bias is invisible here: only claims already extracted are "
        "tested, and what was never extracted is never perturbed.",
        "Model priors are invisible here: removing speaker identity from the input "
        "does not remove what the underlying model associates with the topic.",
    ]
    if unexercised:
        limitations.append(
            "Families not exercised on this sample: "
            + ", ".join(sorted(kind.value for kind in unexercised))
            + "."
        )
    skipped = [run for run in runs if not run.applied]
    if skipped:
        limitations.append(
            f"{len(skipped)} generated run(s) could not be exercised and were excluded "
            "from every rate (for example a single-item evidence set, or a claim no "
            "safe paraphrase rule matched)."
        )
    if not gate.publishable:
        limitations.append(
            "This run did not pass the publishability gate: " + " | ".join(gate.reasons)
        )
    limitations.extend(extra_limitations)

    failures = [
        run.to_example()
        for run in sorted(
            (run for run in applied_runs if run.verdict_changed),
            key=lambda run: (run.claim_id, run.kind.value, run.variant),
        )
    ]

    report = NeutralityReport(
        schema_version=schema_version,
        data_status=data_status,
        generated_at=generated_at,
        report_version=report_version,
        evaluator_version=evaluator_version,
        sample=NeutralitySample(
            claims_tested=len(claim_ids),
            runs_total=len(applied_runs),
            claim_ids=list(claim_ids),
            selection_method=selection_method,
        ),
        perturbations=perturbations,
        metrics=metrics,
        neutrality_health=health,
        neutrality_health_components=components,
        confidence=confidence,
        interpretation_caveat=INTERPRETATION_CAVEAT,
        limitations=limitations,
        failures_to_investigate=failures,
    )
    return report, gate
