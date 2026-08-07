"""Testing Aleph against itself: does a verdict move when it has no reason to?

Everything else in Aleph analyses a document. This package analyses Aleph. It
takes evaluations the pipeline has already produced, changes something that
cannot bear on whether a claim is true — who said it, which outlet carried it,
what party they belong to, whether an institution is named at all, how the
sentence is worded, what order the evidence was listed in — and re-runs the
evaluation. Any change in the verdict is, by construction, a defect: nothing
evidentially relevant was altered.

* :mod:`aleph.neutrality.perturbations` — the six families, as pure functions,
  with a guard that stops a "paraphrase" from quietly changing a number, a
  negation or the direction of a comparison.
* :mod:`aleph.neutrality.runner` — baseline, perturb, re-evaluate, record;
  deterministic, parallel-safe, and keeping a per-run log detailed enough that a
  failure can be argued about rather than merely noticed.
* :mod:`aleph.neutrality.metrics` — ``verdict_flip_rate``, ``confidence_delta``,
  ``framing_delta``, ``explanation_semantic_delta``, the composite
  ``neutrality_health`` with its components, and the gate that marks an analysis
  **not publishable** when the flip rate exceeds its threshold.

**What this proves, and what it does not.** It measures invariance under
irrelevant substitution. It is not proof of political neutrality, and
:data:`~aleph.neutrality.metrics.INTERPRETATION_CAVEAT` travels with every report
saying so. A system can be perfectly invariant here and still be wrong in a
consistent direction — through what it retrieved, through which claims were
extracted for examination at all, or through what the underlying model already
associates with the topic. None of those are visible from inside this suite, and
a good score must never be shown as if they were.
"""

from __future__ import annotations

from aleph.neutrality.metrics import (
    DEFAULT_POLICY,
    HEALTH_WEIGHTS,
    INTERPRETATION_CAVEAT,
    GateResult,
    PerturbationRun,
    PublishabilityPolicy,
    aggregate_metrics,
    build_perturbations,
    build_report,
    check_publishable,
    enforce_publishable,
    explanation_semantic_delta,
    neutrality_confidence,
    neutrality_health,
)
from aleph.neutrality.perturbations import (
    DEFAULT_VOCABULARY,
    PERTURBATION_FUNCTIONS,
    Attribution,
    ClaimContext,
    FieldChange,
    PerturbationOutcome,
    PerturbationVocabulary,
    TruthConditionDriftError,
    assert_truth_conditions_preserved,
    authority_removal,
    claim_paraphrase,
    evidence_order_shuffle,
    generate_perturbations,
    party_swap,
    source_swap,
    speaker_swap,
    truth_conditions_preserved,
)
from aleph.neutrality.runner import (
    REPORT_VERSION,
    EvaluatorUnavailableError,
    NeutralityRunResult,
    RunLogEntry,
    make_claim_context,
    make_reference_evaluator,
    resolve_evaluator,
    run_claim,
    run_suite,
)

__all__ = [
    "DEFAULT_POLICY",
    "DEFAULT_VOCABULARY",
    "HEALTH_WEIGHTS",
    "INTERPRETATION_CAVEAT",
    "PERTURBATION_FUNCTIONS",
    "REPORT_VERSION",
    "Attribution",
    "ClaimContext",
    "EvaluatorUnavailableError",
    "FieldChange",
    "GateResult",
    "NeutralityRunResult",
    "PerturbationOutcome",
    "PerturbationRun",
    "PerturbationVocabulary",
    "PublishabilityPolicy",
    "RunLogEntry",
    "TruthConditionDriftError",
    "aggregate_metrics",
    "assert_truth_conditions_preserved",
    "authority_removal",
    "build_perturbations",
    "build_report",
    "check_publishable",
    "claim_paraphrase",
    "enforce_publishable",
    "evidence_order_shuffle",
    "explanation_semantic_delta",
    "generate_perturbations",
    "make_claim_context",
    "make_reference_evaluator",
    "neutrality_confidence",
    "neutrality_health",
    "party_swap",
    "resolve_evaluator",
    "run_claim",
    "run_suite",
    "source_swap",
    "speaker_swap",
    "truth_conditions_preserved",
]
