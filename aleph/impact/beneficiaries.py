"""Conservative beneficiary and cost-bearer discovery.

The implementation intentionally emits ``uncertain``/``insufficient`` when a
document names a group but does not state a signed effect.  It never upgrades a
mention into a benefit or cost.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from aleph.core.enums import Causality, Direction, EvidenceStrength, Magnitude, TimeHorizon
from aleph.core.models import DocumentModel, GroupImpact, Proposition, TopicGraph


@dataclass(frozen=True, slots=True)
class CausalStep:
    statement: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CausalChain:
    steps: tuple[CausalStep, ...]


@dataclass(frozen=True, slots=True)
class GroupSignal:
    label: str
    terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GroupFinding:
    group: str
    provision_ids: tuple[str, ...]
    direction: Direction = Direction.UNCERTAIN
    causal_chain: CausalChain | None = None


@dataclass(frozen=True, slots=True)
class BeneficiaryAnalysis:
    beneficiaries: tuple[GroupImpact, ...]
    cost_bearers: tuple[GroupImpact, ...]
    findings: tuple[GroupFinding, ...]


STARTER_GROUP_SIGNALS: Final[tuple[GroupSignal, ...]] = (
    GroupSignal("households", ("household", "hogar", "familia")),
    GroupSignal("workers", ("worker", "trabajador", "empleado")),
    GroupSignal("firms", ("firm", "company", "empresa", "employer")),
    GroupSignal("municipalities", ("municipality", "municipio", "local government")),
)


def discover_groups(
    document: DocumentModel,
    graph: TopicGraph | None = None,
    *,
    signals: Sequence[GroupSignal] = STARTER_GROUP_SIGNALS,
) -> tuple[GroupFinding, ...]:
    found: dict[str, set[str]] = {}
    for population in document.affected_populations:
        found.setdefault(population.label, set()).update(population.provision_ids)
    for provision in document.provisions:
        folded = provision.text.casefold()
        for signal in signals:
            if any(term in folded for term in signal.terms):
                found.setdefault(signal.label, set()).add(provision.id)
    return tuple(
        GroupFinding(group=group, provision_ids=tuple(sorted(ids)))
        for group, ids in sorted(found.items())
    )


def build_beneficiary_maps(
    document: DocumentModel,
    propositions: Iterable[Proposition] = (),
    graph: TopicGraph | None = None,
) -> BeneficiaryAnalysis:
    """Return only signed effects; preserve unsigned mentions as findings."""
    del propositions
    findings = discover_groups(document, graph)
    beneficiaries: list[GroupImpact] = []
    cost_bearers: list[GroupImpact] = []
    for finding in findings:
        if finding.direction not in {Direction.POSITIVE, Direction.NEGATIVE}:
            continue
        impact = GroupImpact(
            group=finding.group,
            estimated_direction=finding.direction,
            magnitude=Magnitude.UNKNOWN,
            evidence_quality=EvidenceStrength.INSUFFICIENT,
            time_horizon=TimeHorizon.UNKNOWN,
            direct_or_indirect=Causality.UNKNOWN,
            supporting_evidence=[],
            rationale=(
                "The document names this group, but the available record does not quantify "
                "the effect; direction is retained only when explicitly stated."
            ),
        )
        (beneficiaries if finding.direction is Direction.POSITIVE else cost_bearers).append(impact)
    return BeneficiaryAnalysis(tuple(beneficiaries), tuple(cost_bearers), findings)
