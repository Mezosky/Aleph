"""Running the suite: baseline, perturb, re-evaluate, record the difference.

The harness is deliberately dumb, and that is a design property rather than a
limitation. For each claim it takes one baseline blind evaluation, generates the
six families of substitutions, re-evaluates each one, and writes down what
changed. It never decides whether a change was *justified*, because under these
substitutions no change ever is: the proposition and the evidence are held fixed
by construction, so every difference is a defect and the harness's only job is to
be an honest witness to it.

Three properties the implementation is built around:

**Determinism.** Claims are processed in sorted id order, families in the fixed
order of :class:`~aleph.core.enums.PerturbationKind`, variants in ascending
order, and every substitution is hash-selected rather than sampled. Two runs of
the same suite over the same claims produce identical output, so a diff between
two neutrality reports shows a change in Aleph and never a change in luck.

**Parallel-safety.** Work is partitioned by claim and every function it calls is
pure, so claims may be evaluated concurrently — subject to the evaluator itself
being thread-safe, which is the caller's guarantee to make. Results are
reassembled in sorted order before anything is measured, so concurrency cannot
reach the numbers. The default is a single worker, because the usual bottleneck
is a rate-limited model endpoint and quiet parallelism there would be rude.

**Debuggability.** A flip that a maintainer cannot reproduce is a flip that gets
explained away. Every run keeps a :class:`RunLogEntry` holding both claim texts,
both evidence orderings, both attributive frames, both verdicts, both confidences
and both full explanations. The aggregate says a family is failing; the log says
which sentence, in which direction, with what swapped for what.

The evaluator under test is :func:`aleph.claims.evaluate.evaluate_blind`, imported
lazily inside :func:`resolve_evaluator` so that this module imports cleanly in a
partially-built tree and so that a caller can inject a different evaluator
without the real one ever being loaded.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from aleph.core.enums import DataStatus, PerturbationKind, Verdict, WithheldCategory
from aleph.core.errors import AlephError
from aleph.core.ids import stable_hash
from aleph.core.models import (
    DEFAULT_WITHHELD,
    BlindEvaluation,
    Confidence,
    NeutralityReport,
    RedactedClaimContext,
    RedactedContext,
)
from aleph.neutrality.metrics import (
    DEFAULT_POLICY,
    GateResult,
    PerturbationRun,
    PublishabilityPolicy,
    build_report,
    explanation_semantic_delta,
)
from aleph.neutrality.perturbations import (
    DEFAULT_VOCABULARY,
    Attribution,
    ClaimContext,
    PerturbationOutcome,
    PerturbationVocabulary,
    generate_perturbations,
)

__all__ = [
    "REPORT_VERSION",
    "BlindEvaluatorFn",
    "EvaluatorUnavailableError",
    "FramingScorer",
    "NeutralityRunResult",
    "RunLogEntry",
    "make_reference_evaluator",
    "resolve_evaluator",
    "run_claim",
    "run_suite",
    "utc_now",
]

#: Version of this harness. Neutrality results are only comparable across runs of
#: the same harness version, which is why the schema requires it to travel with
#: the numbers.
REPORT_VERSION: Final[str] = "aleph-neutrality/1.0.0"

BlindEvaluatorFn = Callable[[RedactedClaimContext], BlindEvaluation]

#: Scores the framing of one evaluation on a 0-100 scale. Injected rather than
#: imported: framing lives in :mod:`aleph.framing` and the neutrality suite must
#: be runnable — and testable — without it.
FramingScorer = Callable[[ClaimContext, BlindEvaluation], float]


class EvaluatorUnavailableError(AlephError):
    """The evaluator under test could not be loaded or called.

    Raised rather than silently substituting a stand-in. A neutrality report
    naming an evaluator that never ran would be the most misleading artefact this
    system could produce: it would certify, with numbers, a property of code that
    was not exercised.
    """


def utc_now() -> str:
    """Current instant as a contract-shaped UTC timestamp.

    Callers who need byte-identical output across runs should pass an explicit
    ``generated_at`` instead: this is the one non-deterministic value in the whole
    module, and it is isolated here so that fact is easy to see.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Resolving the evaluator under test
# ---------------------------------------------------------------------------


def resolve_evaluator(evaluator: BlindEvaluatorFn | None = None) -> BlindEvaluatorFn:
    """Return the evaluator to test, importing the real one only if needed.

    The import is deliberately inside the function body. :mod:`aleph.claims` is
    built alongside this package, and a module-level import would make the whole
    neutrality suite unimportable — including its own tests — whenever that
    package is mid-change.

    If ``evaluate_blind`` requires a ``provider`` argument, the configured
    provider is bound. Any *other* required argument is an error: the contract
    signature takes a :class:`~aleph.core.models.RedactedClaimContext` and
    nothing else, and an evaluator needing more input is an evaluator with more
    ways for identity to reach it.
    """
    if evaluator is not None:
        return evaluator

    try:
        from aleph.claims.evaluate import evaluate_blind
    except ImportError as exc:  # pragma: no cover - depends on build order
        raise EvaluatorUnavailableError(
            "aleph.claims.evaluate.evaluate_blind could not be imported; pass an "
            "explicit evaluator to run the neutrality suite",
            detail=str(exc),
        ) from exc

    try:
        signature = inspect.signature(evaluate_blind)
    except (TypeError, ValueError):  # pragma: no cover - builtins and C callables
        return evaluate_blind

    parameters = list(signature.parameters.values())[1:]
    unfilled = [
        parameter.name
        for parameter in parameters
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    ]
    if not unfilled:
        return evaluate_blind
    if unfilled == ["provider"]:
        from aleph.llm import get_provider

        return functools.partial(evaluate_blind, provider=get_provider())
    raise EvaluatorUnavailableError(
        "evaluate_blind requires arguments the harness cannot supply",
        required=unfilled,
        expected_signature="evaluate_blind(context: RedactedClaimContext) -> BlindEvaluation",
    )


# ---------------------------------------------------------------------------
# The per-run log
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunLogEntry:
    """Everything needed to reproduce and argue about one perturbed run.

    Deliberately verbose. The aggregate tells a maintainer that
    ``authority_removal`` is failing; only this tells them that it fails on the
    two claims whose evidence is a single technical report, and that the
    explanation stopped citing the figure the moment the institution's name came
    off.
    """

    claim_id: str
    kind: PerturbationKind
    variant: int
    applied: bool
    description: str
    substitution: str
    baseline_claim_text: str
    perturbed_claim_text: str
    baseline_attribution: str
    perturbed_attribution: str
    baseline_evidence_order: tuple[str, ...]
    perturbed_evidence_order: tuple[str, ...]
    baseline_verdict: Verdict
    perturbed_verdict: Verdict
    baseline_confidence: float
    perturbed_confidence: float
    baseline_reasoning: str
    perturbed_reasoning: str
    explanation_semantic_delta: float
    framing_delta: float | None
    note: str | None = None

    @property
    def verdict_changed(self) -> bool:
        return self.applied and self.baseline_verdict != self.perturbed_verdict

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "perturbation": self.kind.value,
            "variant": self.variant,
            "applied": self.applied,
            "verdict_changed": self.verdict_changed,
            "description": self.description,
            "substitution": self.substitution,
            "claim_text": {
                "baseline": self.baseline_claim_text,
                "perturbed": self.perturbed_claim_text,
            },
            "attribution": {
                "baseline": self.baseline_attribution,
                "perturbed": self.perturbed_attribution,
            },
            "evidence_order": {
                "baseline": list(self.baseline_evidence_order),
                "perturbed": list(self.perturbed_evidence_order),
            },
            "verdict": {
                "baseline": self.baseline_verdict.value,
                "perturbed": self.perturbed_verdict.value,
            },
            "evidence_confidence": {
                "baseline": self.baseline_confidence,
                "perturbed": self.perturbed_confidence,
                "delta": round(self.perturbed_confidence - self.baseline_confidence, 6),
            },
            "reasoning": {
                "baseline": self.baseline_reasoning,
                "perturbed": self.perturbed_reasoning,
            },
            "explanation_semantic_delta": self.explanation_semantic_delta,
            "framing_delta": self.framing_delta,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class NeutralityRunResult:
    """The complete outcome of a suite run.

    Carries the publishable report, the gate decision, the metric-level runs and
    the full log. The gate travels with the report so a caller cannot pick up the
    numbers without also picking up the decision they imply.
    """

    report: NeutralityReport
    gate: GateResult
    runs: tuple[PerturbationRun, ...]
    log: tuple[RunLogEntry, ...]
    baselines: Mapping[str, BlindEvaluation]

    @property
    def publishable(self) -> bool:
        return self.gate.publishable

    def failures(self) -> tuple[RunLogEntry, ...]:
        """Log entries where the verdict moved. The first thing to read."""
        return tuple(entry for entry in self.log if entry.verdict_changed)

    def log_as_jsonable(self) -> list[dict[str, Any]]:
        return [entry.to_jsonable() for entry in self.log]


# ---------------------------------------------------------------------------
# Running one claim
# ---------------------------------------------------------------------------


def run_claim(
    context: ClaimContext,
    evaluator: BlindEvaluatorFn,
    *,
    vocabulary: PerturbationVocabulary = DEFAULT_VOCABULARY,
    kinds: Sequence[PerturbationKind] | None = None,
    variants_per_kind: int = 1,
    framing_scorer: FramingScorer | None = None,
    withheld: Sequence[WithheldCategory] = DEFAULT_WITHHELD,
) -> tuple[BlindEvaluation, tuple[PerturbationRun, ...], tuple[RunLogEntry, ...]]:
    """Evaluate one claim at baseline and under every perturbation.

    The baseline is evaluated first and exactly once; every family is compared
    against that same baseline rather than against each other, so the six results
    are independent and a single bad baseline cannot cascade.

    Returns:
        ``(baseline_evaluation, runs, log_entries)``.
    """
    baseline_evaluation = _evaluate(context, evaluator, withheld=withheld)
    baseline_framing = (
        framing_scorer(context, baseline_evaluation) if framing_scorer is not None else None
    )

    runs: list[PerturbationRun] = []
    log: list[RunLogEntry] = []

    for outcome in generate_perturbations(
        context,
        vocabulary=vocabulary,
        kinds=kinds,
        variants_per_kind=variants_per_kind,
    ):
        run, entry = _compare(
            context,
            baseline_evaluation,
            baseline_framing,
            outcome,
            evaluator,
            framing_scorer=framing_scorer,
            withheld=withheld,
        )
        runs.append(run)
        log.append(entry)

    return baseline_evaluation, tuple(runs), tuple(log)


def _evaluate(
    context: ClaimContext,
    evaluator: BlindEvaluatorFn,
    *,
    withheld: Sequence[WithheldCategory],
) -> BlindEvaluation:
    redacted = context.to_redacted_context(withheld=withheld)
    try:
        evaluation = evaluator(redacted)
    except AlephError:
        raise
    except Exception as exc:  # noqa: BLE001 - any evaluator failure is reportable
        raise EvaluatorUnavailableError(
            "the evaluator under test raised while evaluating a claim",
            claim_id=context.claim_id,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
    if not isinstance(evaluation, BlindEvaluation):
        raise EvaluatorUnavailableError(
            "the evaluator under test did not return a BlindEvaluation",
            claim_id=context.claim_id,
            returned=type(evaluation).__name__,
        )
    return evaluation


def _compare(
    baseline_context: ClaimContext,
    baseline_evaluation: BlindEvaluation,
    baseline_framing: float | None,
    outcome: PerturbationOutcome,
    evaluator: BlindEvaluatorFn,
    *,
    framing_scorer: FramingScorer | None,
    withheld: Sequence[WithheldCategory],
) -> tuple[PerturbationRun, RunLogEntry]:
    """Evaluate one perturbed context and record the difference from baseline.

    A perturbation the harness could not apply is still evaluated and still
    logged — the log is a record of what was attempted — but is marked
    ``applied=False`` so it is excluded from every rate downstream. That
    distinction is the difference between "this family found no instability" and
    "this family never ran".
    """
    if outcome.applied:
        perturbed_evaluation = _evaluate(outcome.context, evaluator, withheld=withheld)
    else:
        perturbed_evaluation = baseline_evaluation

    perturbed_framing = (
        framing_scorer(outcome.context, perturbed_evaluation)
        if framing_scorer is not None
        else None
    )
    framing_delta = (
        None
        if baseline_framing is None or perturbed_framing is None
        else round(perturbed_framing - baseline_framing, 6)
    )

    semantic_delta = explanation_semantic_delta(
        baseline_evaluation.reasoning, perturbed_evaluation.reasoning
    )

    run = PerturbationRun(
        claim_id=baseline_context.claim_id,
        kind=outcome.kind,
        variant=outcome.variant,
        substitution=outcome.substitution,
        description=outcome.description,
        baseline_verdict=baseline_evaluation.verdict,
        perturbed_verdict=perturbed_evaluation.verdict,
        baseline_confidence=baseline_evaluation.confidence.evidence_confidence,
        perturbed_confidence=perturbed_evaluation.confidence.evidence_confidence,
        explanation_semantic_delta=semantic_delta,
        framing_delta=framing_delta,
        applied=outcome.applied,
        note=outcome.note,
    )
    entry = RunLogEntry(
        claim_id=baseline_context.claim_id,
        kind=outcome.kind,
        variant=outcome.variant,
        applied=outcome.applied,
        description=outcome.description,
        substitution=outcome.substitution,
        baseline_claim_text=baseline_context.claim_text,
        perturbed_claim_text=outcome.context.claim_text,
        baseline_attribution=baseline_context.attribution.describe(),
        perturbed_attribution=outcome.context.attribution.describe(),
        baseline_evidence_order=tuple(item.id for item in baseline_context.evidence),
        perturbed_evidence_order=tuple(item.id for item in outcome.context.evidence),
        baseline_verdict=baseline_evaluation.verdict,
        perturbed_verdict=perturbed_evaluation.verdict,
        baseline_confidence=baseline_evaluation.confidence.evidence_confidence,
        perturbed_confidence=perturbed_evaluation.confidence.evidence_confidence,
        baseline_reasoning=baseline_evaluation.reasoning,
        perturbed_reasoning=perturbed_evaluation.reasoning,
        explanation_semantic_delta=semantic_delta,
        framing_delta=framing_delta,
        note=outcome.note,
    )
    return run, entry


# ---------------------------------------------------------------------------
# Running the suite
# ---------------------------------------------------------------------------


def run_suite(
    contexts: Iterable[ClaimContext],
    *,
    evaluator: BlindEvaluatorFn | None = None,
    vocabulary: PerturbationVocabulary = DEFAULT_VOCABULARY,
    kinds: Sequence[PerturbationKind] | None = None,
    variants_per_kind: int = 1,
    framing_scorer: FramingScorer | None = None,
    policy: PublishabilityPolicy | None = None,
    withheld: Sequence[WithheldCategory] = DEFAULT_WITHHELD,
    generated_at: str | None = None,
    report_version: str = REPORT_VERSION,
    evaluator_version: str | None = None,
    data_status: DataStatus = DataStatus.SYNTHETIC,
    schema_version: str = "1.0.0",
    selection_method: str | None = None,
    max_examples_per_kind: int = 3,
    max_workers: int = 1,
) -> NeutralityRunResult:
    """Run the full suite and assemble the report and the publishability gate.

    Args:
        contexts: Claims to test, with their evidence and attributive frames.
            Processed in sorted id order regardless of the order supplied.
        evaluator: The evaluator under test. ``None`` resolves
            :func:`aleph.claims.evaluate.evaluate_blind`.
        vocabulary: Substitution pools. Jurisdiction-specific vocabularies belong
            in a registry data file and arrive through this argument.
        kinds: Restrict to a subset of families. Doing so makes the run
            unpublishable by default, since an unexercised family's zero flips
            prove nothing — which is exactly what the gate will say.
        variants_per_kind: How many substitutions per family per claim. More
            variants make the rate less hostage to one unlucky draw.
        framing_scorer: Optional 0-100 framing score. Without it,
            ``framing_delta`` is reported as zero and named in ``limitations`` as
            not exercised, rather than being quietly presented as a pass.
        policy: Publishability thresholds. See
            :class:`~aleph.neutrality.metrics.PublishabilityPolicy`.
        generated_at: Timestamp for the report. Pass a fixed value for a
            byte-reproducible bundle.
        max_workers: Threads across claims. Requires a thread-safe evaluator.
            Results are reordered deterministically before any measurement, so
            this cannot affect the numbers.

    Returns:
        A :class:`NeutralityRunResult` holding the report, the gate decision, the
        per-run metrics and the full debugging log.
    """
    ordered = sorted(contexts, key=lambda ctx: (ctx.claim_id,))
    if variants_per_kind < 1:
        raise ValueError("variants_per_kind must be at least 1")

    active_evaluator = resolve_evaluator(evaluator)
    worker = functools.partial(
        run_claim,
        evaluator=active_evaluator,
        vocabulary=vocabulary,
        kinds=kinds,
        variants_per_kind=variants_per_kind,
        framing_scorer=framing_scorer,
        withheld=withheld,
    )

    if max_workers > 1 and len(ordered) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            outcomes = list(pool.map(worker, ordered))
    else:
        outcomes = [worker(context) for context in ordered]

    baselines: dict[str, BlindEvaluation] = {}
    runs: list[PerturbationRun] = []
    log: list[RunLogEntry] = []
    for context, (baseline, claim_runs, claim_log) in zip(ordered, outcomes, strict=True):
        baselines[context.claim_id] = baseline
        runs.extend(claim_runs)
        log.extend(claim_log)

    report, gate = build_report(
        runs,
        claim_ids=[context.claim_id for context in ordered],
        generated_at=generated_at or utc_now(),
        report_version=report_version,
        evaluator_version=evaluator_version or _evaluator_version(baselines.values()),
        data_status=data_status,
        schema_version=schema_version,
        selection_method=selection_method
        or (
            f"exhaustive over the supplied claim set, {variants_per_kind} variant(s) per "
            "perturbation family, substitutions selected by content hash (no sampling)"
        ),
        policy=policy or DEFAULT_POLICY,
        max_examples_per_kind=max_examples_per_kind,
        extra_limitations=(
            ()
            if framing_scorer is not None
            else (
                "framing_delta was not exercised: no framing scorer was supplied, so "
                "its reported value of 0 means 'not measured', not 'no change'.",
            )
        ),
    )
    return NeutralityRunResult(
        report=report,
        gate=gate,
        runs=tuple(runs),
        log=tuple(log),
        baselines=baselines,
    )


def _evaluator_version(evaluations: Iterable[BlindEvaluation]) -> str:
    """Read the evaluator version off the evaluations themselves.

    A neutrality result belongs to one specific evaluator and is invalidated the
    moment that evaluator changes, so the version is taken from what actually
    ran rather than from what the caller believed was running. A mixed set is
    reported as mixed instead of being silently reduced to the first value.
    """
    versions = sorted({evaluation.evaluator_version for evaluation in evaluations})
    if not versions:
        return "unknown"
    if len(versions) == 1:
        return versions[0]
    return f"mixed:{stable_hash(*versions, length=12)}"


# ---------------------------------------------------------------------------
# Reference evaluators — for exercising the harness, never for publication
# ---------------------------------------------------------------------------


def make_reference_evaluator(
    *,
    leaks_attribution: bool = False,
    evaluator_version: str = "aleph-reference-evaluator/1.0.0",
) -> BlindEvaluatorFn:
    """Build a deterministic stand-in evaluator, for testing the harness itself.

    **This is not a fact-checker and must never produce a published report.** It
    derives a verdict by hashing the evidence ids and knows nothing about truth.
    It exists because a measuring instrument has to be calibrated against a known
    signal before its readings mean anything:

    * with ``leaks_attribution=False`` it is invariant by construction — it never
      reads the claim text or the attributive frame — so any flip the suite
      reports against it is a bug in the *harness*;
    * with ``leaks_attribution=True`` it deliberately keys its verdict off the
      attribution line, so a suite that reports a clean run against it is a
      harness that cannot detect the failure it exists to detect.

    A neutrality suite that has never been shown to fail is not evidence of
    anything, and this is how it is shown to fail.
    """

    def evaluate(context: RedactedClaimContext) -> BlindEvaluation:
        evidence_ids = sorted(item.id for item in context.evidence)
        parts: list[str] = ["reference", *evidence_ids]
        if leaks_attribution:
            parts.extend(context.context_excerpts)
        digest = stable_hash(*parts, length=8)
        verdicts = (
            Verdict.SUPPORTED,
            Verdict.PARTIALLY_SUPPORTED,
            Verdict.UNSUPPORTED,
            Verdict.UNVERIFIABLE,
        )
        verdict = verdicts[int(digest, 16) % len(verdicts)]
        confidence_value = round(0.35 + (int(digest[:4], 16) % 500) / 1000.0, 4)
        redacted: RedactedContext = context.to_redacted_context()
        cited = ", ".join(evidence_ids) if evidence_ids else "no evidence items"
        return BlindEvaluation(
            evaluator_version=evaluator_version,
            redacted_context=redacted,
            verdict=verdict,
            reasoning=(
                f"Reference harness evaluator: the assessment is derived from the "
                f"identity of the evidence set ({cited}) and carries no factual "
                f"content. Verdict {verdict.value} recorded for calibration only."
            ),
            evidence_refs=list(evidence_ids),
            confidence=Confidence(evidence_confidence=min(confidence_value, 1.0)),
        )

    return evaluate


def make_claim_context(
    claim_id: str,
    claim_text: str,
    *,
    evidence: Sequence[Any] = (),
    context_excerpts: Sequence[str] = (),
    made_at: str | None = None,
    speaker_role: str | None = None,
    party_label: str | None = None,
    outlet_name: str | None = None,
    institution: str | None = None,
) -> ClaimContext:
    """Convenience constructor for a claim under test.

    Kept here rather than on :class:`ClaimContext` so the dataclass stays a plain
    value object. The attribution arguments are generic role descriptions; the
    harness must never be handed a real person's name, and there is no code path
    here that would put one in front of an evaluator.
    """
    return ClaimContext(
        claim_id=claim_id,
        claim_text=claim_text,
        evidence=tuple(evidence),
        context_excerpts=tuple(context_excerpts),
        made_at=made_at,
        attribution=Attribution(
            speaker_role=speaker_role,
            party_label=party_label,
            outlet_name=outlet_name,
            institution=institution,
        ),
    )
