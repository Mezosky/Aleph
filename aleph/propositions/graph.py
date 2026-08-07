"""Warm phase 3 — the semantic graph that makes the middle of an argument visible.

"This measure helps small firms" is four words hiding three separate questions:
*which provision*, *through what mechanism*, *on which group*. As prose, none of
them can be checked — the sentence is either accepted or disbelieved as a whole.
Split into typed nodes and typed edges, each step has to be stated on the record
and each one becomes independently arguable: a reader can accept that the
provision exists, accept that it names that group, and still reject the claimed
mechanism.

The graph is built from what phase 1 read out of the document and what phase 2
decomposed it into. It asserts nothing the document did not, and where Aleph
draws a conclusion the document only implies — that the group a levy names is the
group that pays it — the edge is marked ``document_implicit`` rather than
``document_explicit``. That distinction is not decoration: presenting Aleph's
inference as the document's own statement would misattribute Aleph's reasoning to
the source, which is the same failure as a misquote.

Four properties are enforced here rather than left to callers.

**Entity resolution is generic and merges co-referents.** ``SERVICIO RECAUDADOR
NACIONAL``, ``Servicio Recaudador Nacional`` and ``el Servicio Recaudador
Nacional S.A.`` are one body, and a graph that shows three is not a graph of the
document — it is a graph of its typography. Folding is by case, accent,
determiner, legal-form suffix and auto-detected acronym, all of which are
properties of writing rather than of any jurisdiction.

**Every edge names its evidence and its confidence.** An edge is a claim in
miniature and is held to the claim standard.

**Effects are directional and coarse.** ``direction`` plus ``magnitude``, never a
number, and never a position on a political axis — there is no such axis anywhere
in this module.

**Ordering is total and deterministic.** Nodes and edges are sorted by id, and ids
are pure functions of their content, so re-analysing a document produces a diff
that shows what changed in the analysis rather than what changed in a dict's
iteration order.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from aleph.core.enums import (
    Causality,
    ConfidenceEffect,
    ConfidenceFactor,
    DataStatus,
    Direction,
    EdgeBasis,
    EdgeKind,
    InstitutionRole,
    Magnitude,
    NodeKind,
    PropositionType,
    ProvenanceSourceKind,
    ProvisionType,
    TimeHorizon,
)
from aleph.core.ids import edge_id, id_parts, node_id, slugify
from aleph.core.models import (
    SCHEMA_VERSION,
    Confidence,
    ConfidenceBasis,
    DocumentModel,
    GraphEdge,
    GraphNode,
    GraphStats,
    NodeAttribute,
    Proposition,
    PropositionSet,
    Provenance,
    Provision,
    Span,
    TopicGraph,
)

__all__ = [
    "GRAPH_BUILDER_VERSION",
    "EntityResolver",
    "build_entity_resolver",
    "ACRONYM_INTRO_RE",
    "acronym_matches",
    "ARTICLES",
    "LEGAL_FORM_SUFFIXES",
    "PROVISION_INSTRUMENT_KIND",
    "PROVISION_INCIDENCE",
    "build_topic_graph",
    "Neighbour",
    "neighbours",
    "subgraph_for_provision",
    "NodeDegree",
    "degree_table",
    "centrality",
    "NodeRanking",
    "rank_nodes",
    "graph_stats",
]

GRAPH_BUILDER_VERSION: Final[str] = "1.0.0"


# ---------------------------------------------------------------------------
# Entity resolution
#
# The vocabularies below describe how names are *written*, not what they name.
# A determiner and a company-form suffix are facts about orthography in a family
# of languages; neither encodes a jurisdiction, an institution or a subject, and
# nothing downstream branches on which of them fired.
# ---------------------------------------------------------------------------

ARTICLES: Final[frozenset[str]] = frozenset(
    """the a an el la los las un una unos unas lo le les il lo gli i o os as um uma der die das
    den dem des ein eine einer eines de du l' d'""".split()
)

LEGAL_FORM_SUFFIXES: Final[frozenset[str]] = frozenset(
    """sa s.a s.a. sas s.a.s srl s.r.l spa s.p.a sl s.l ltda ltd ltd. limited inc inc. incorporated
    llc plc gmbh mbh ag nv n.v bv b.v oy ab a/s aps as kg ohg sarl s.a.r.l pty corp corp.
    corporation co co. company kft doo d.o.o zoo sp sp. eirl""".split()
)

_PARENTHETICAL_RE: Final[re.Pattern[str]] = re.compile(r"\s*[(\[]([^()\[\]]{1,80})[)\]]")
_NON_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[^\w\s]+", re.UNICODE)
_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

#: ``Long Descriptive Name (LDN)`` — the pattern by which documents introduce
#: their own abbreviations. Detecting it is what lets an acronym used later in
#: the text resolve to the same node as its expansion.
ACRONYM_INTRO_RE: Final[re.Pattern[str]] = re.compile(
    r"([^\s(){}\[\]][^(){}\[\]]{4,90}?)\s*[(\[]\s*([^\W\d_]{2,10})\s*[)\]]",
    re.UNICODE,
)


def _fold(text: str) -> str:
    """Case- and accent-folded form. The basis of every comparison in this module."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


@dataclass(frozen=True, slots=True)
class EntityResolver:
    """Decides when two surface forms name the same thing.

    Merging is conservative in one specific direction: it will happily unify
    spellings, but it will not unify two names that differ in any content word.
    Over-merging is the dangerous error — it would attribute one body's
    obligations to another and produce a graph that misstates who must do what —
    whereas under-merging leaves two nodes that a reader can see are the same.

    ``abbreviations`` is mined from the document itself rather than supplied, so
    the resolver learns each document's own short forms and imports no
    jurisdiction-specific list.
    """

    abbreviations: Mapping[str, str] = field(default_factory=dict)
    """Folded acronym → folded expansion, from ``Long Name (LN)`` in the text."""
    articles: frozenset[str] = ARTICLES
    legal_forms: frozenset[str] = LEGAL_FORM_SUFFIXES

    def strip_parentheticals(self, label: str) -> tuple[str, list[str]]:
        """Split ``Name (Alias)`` into the name and the parenthetical aliases."""
        aliases = [m.group(1).strip() for m in _PARENTHETICAL_RE.finditer(label)]
        stem = _PARENTHETICAL_RE.sub(" ", label)
        return _WS_RE.sub(" ", stem).strip(), [a for a in aliases if a]

    def key(self, label: str) -> str:
        """Return the canonical key two co-referent labels share.

        Empty input, or input that folds away entirely, returns ``""`` — the
        caller must treat that as "unresolvable" and skip the node rather than
        create one keyed on nothing, which would merge every unnameable entity
        into a single false node.
        """
        stem, _ = self.strip_parentheticals(label)
        folded = _fold(stem)
        cleaned = _WS_RE.sub(" ", _NON_WORD_RE.sub(" ", folded)).strip()
        tokens = [t for t in cleaned.split() if t]
        while tokens and tokens[0] in self.articles:
            tokens.pop(0)
        tokens = [t for t in tokens if t not in self.legal_forms]
        if not tokens:
            return ""
        if len(tokens) == 1:
            expansion = self.abbreviations.get(tokens[0])
            if expansion:
                return self.key(expansion)
        return "-".join(tokens)


def build_entity_resolver(document: DocumentModel) -> EntityResolver:
    """Mine a document for its own abbreviations and build a resolver from them.

    Only ``Long Name (LN)`` introductions whose letters actually match the
    initials of the expansion are accepted. Without that check, every
    parenthetical in the document — a cross-reference, a unit, a clarification —
    would be registered as an abbreviation, and the resolver would start merging
    unrelated entities, which is the one error it must not make.
    """
    corpus: list[str] = [document.identity.title]
    if document.identity.subtitle:
        corpus.append(document.identity.subtitle)
    corpus.extend(section.heading for section in _walk_sections(document))
    corpus.extend(provision.title or "" for provision in document.provisions)
    corpus.extend(provision.text for provision in document.provisions)
    corpus.extend(entry.name for entry in document.affected_institutions)
    corpus.extend(definition.definition_text for definition in document.definitions)

    found: dict[str, str] = {}
    for chunk in corpus:
        if not chunk:
            continue
        for match in ACRONYM_INTRO_RE.finditer(chunk):
            expansion, acronym = match.group(1).strip(), match.group(2).strip()
            if not acronym_matches(acronym, expansion):
                continue
            key = _fold(acronym)
            # First introduction wins, and ties are broken lexicographically so
            # two runs over the same text agree.
            candidate = expansion
            if key not in found or candidate < found[key]:
                found[key] = candidate
    return EntityResolver(abbreviations={k: _fold(v) for k, v in sorted(found.items())})


def acronym_matches(acronym: str, expansion: str) -> bool:
    """Whether ``acronym`` is plausibly built from the initials of ``expansion``.

    Function words may be skipped — most acronyms drop them — but every letter of
    the acronym must be consumed in order by the initials of the remaining words.
    """
    letters = [ch for ch in _fold(acronym) if ch.isalpha()]
    if len(letters) < 2:
        return False
    words = [w for w in _NON_WORD_RE.sub(" ", _fold(expansion)).split() if w]
    if len(words) < len(letters):
        return False
    index = 0
    for word in words:
        if index < len(letters) and word[0] == letters[index]:
            index += 1
    return index == len(letters)


def _walk_sections(document: DocumentModel) -> list:
    out = []
    stack = list(document.structure.sections)
    while stack:
        section = stack.pop()
        out.append(section)
        stack.extend(section.children)
    return out


# ---------------------------------------------------------------------------
# Provision → relation mapping
#
# Structural, not evaluative. The tables say what *kind* of relation a provision
# type creates and which way the burden or the benefit falls. They say nothing
# about whether any of it is a good idea, and there is no axis here on which such
# a judgement could be recorded.
# ---------------------------------------------------------------------------

PROVISION_INSTRUMENT_KIND: Final[dict[ProvisionType, NodeKind]] = {
    ProvisionType.TAX: NodeKind.TAX,
    ProvisionType.FEE: NodeKind.TAX,
    ProvisionType.BENEFIT: NodeKind.BENEFIT,
    ProvisionType.SUBSIDY: NodeKind.BENEFIT,
    ProvisionType.ENTITLEMENT: NodeKind.BENEFIT,
    ProvisionType.OBLIGATION: NodeKind.OBLIGATION,
    ProvisionType.PROHIBITION: NodeKind.OBLIGATION,
    ProvisionType.REPORTING_REQUIREMENT: NodeKind.OBLIGATION,
    ProvisionType.SANCTION: NodeKind.OBLIGATION,
    ProvisionType.PERMISSION: NodeKind.RIGHT,
    ProvisionType.ELIGIBILITY_CRITERION: NodeKind.RIGHT,
}
"""Provision types that bring a named instrument into being.

An instrument node is created for these so that several provisions touching one
levy or one entitlement converge on a single thing a reader can follow, instead
of being scattered across clause numbers.
"""

PROVISION_INCIDENCE: Final[dict[ProvisionType, tuple[EdgeKind, Direction]]] = {
    ProvisionType.TAX: (EdgeKind.TAXES, Direction.NEGATIVE),
    ProvisionType.FEE: (EdgeKind.TAXES, Direction.NEGATIVE),
    ProvisionType.BENEFIT: (EdgeKind.BENEFITS, Direction.POSITIVE),
    ProvisionType.SUBSIDY: (EdgeKind.BENEFITS, Direction.POSITIVE),
    ProvisionType.ENTITLEMENT: (EdgeKind.BENEFITS, Direction.POSITIVE),
    ProvisionType.FUNDING_ALLOCATION: (EdgeKind.FUNDS, Direction.POSITIVE),
    ProvisionType.OBLIGATION: (EdgeKind.RESTRICTS, Direction.NEGATIVE),
    ProvisionType.PROHIBITION: (EdgeKind.RESTRICTS, Direction.NEGATIVE),
    ProvisionType.REPORTING_REQUIREMENT: (EdgeKind.RESTRICTS, Direction.NEGATIVE),
    ProvisionType.SANCTION: (EdgeKind.COSTS, Direction.NEGATIVE),
    ProvisionType.PERMISSION: (EdgeKind.EXPANDS, Direction.POSITIVE),
    ProvisionType.ELIGIBILITY_CRITERION: (EdgeKind.EXPANDS, Direction.UNCERTAIN),
    ProvisionType.INSTITUTIONAL_MANDATE: (EdgeKind.REGULATES, Direction.NONE),
    ProvisionType.PROCEDURE: (EdgeKind.REGULATES, Direction.NONE),
    ProvisionType.DELEGATION: (EdgeKind.REGULATES, Direction.NONE),
    ProvisionType.REPEAL: (EdgeKind.REPLACES, Direction.NONE),
    ProvisionType.AMENDMENT: (EdgeKind.MODIFIES, Direction.NONE),
}
"""How a provision type falls on the parties it names.

``restricts`` with a negative direction on an obligation is a statement about
incidence — a duty is a burden on whoever bears it — not a statement that the
duty is unwarranted. ``magnitude`` is left ``unknown`` on all of these precisely
so that direction is never mistaken for a measurement.
"""

_DEFAULT_INCIDENCE: Final[tuple[EdgeKind, Direction]] = (EdgeKind.AFFECTS, Direction.UNCERTAIN)

_PARTY_KINDS: Final[frozenset[NodeKind]] = frozenset(
    {
        NodeKind.SOCIAL_GROUP,
        NodeKind.SECTOR,
        NodeKind.INSTITUTION,
        NodeKind.COMPANY,
        NodeKind.REGION,
    }
)

_INSTITUTION_EDGE: Final[dict[InstitutionRole, tuple[EdgeKind, Direction]]] = {
    InstitutionRole.IMPLEMENTING: (EdgeKind.REGULATES, Direction.NONE),
    InstitutionRole.SUPERVISING: (EdgeKind.REGULATES, Direction.NONE),
    InstitutionRole.FUNDING: (EdgeKind.FUNDS, Direction.POSITIVE),
    InstitutionRole.REPORTING: (EdgeKind.RESTRICTS, Direction.NEGATIVE),
    InstitutionRole.CONSULTED: (EdgeKind.AFFECTS, Direction.NONE),
    InstitutionRole.BENEFICIARY: (EdgeKind.BENEFITS, Direction.POSITIVE),
    InstitutionRole.REGULATED: (EdgeKind.REGULATES, Direction.NEGATIVE),
    InstitutionRole.CREATED: (EdgeKind.EXPANDS, Direction.POSITIVE),
    InstitutionRole.ABOLISHED: (EdgeKind.REPLACES, Direction.NEGATIVE),
    InstitutionRole.OTHER: (EdgeKind.AFFECTS, Direction.UNCERTAIN),
}


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _NodeDraft:
    """Accumulator for one resolved entity before it becomes a :class:`GraphNode`.

    Surface forms are counted rather than merely collected: the label a reader
    sees is the spelling the document used most often, which is the one they will
    recognise. Ties break lexicographically so the choice is reproducible.
    """

    key: str
    kind: NodeKind
    surfaces: dict[str, int] = field(default_factory=dict)
    preferred: str | None = None
    """The first surface form registered. Breaks ties in favour of the name the
    entity was introduced under, which beats alphabetical order — otherwise an
    acronym or a file number would routinely out-sort the name a reader knows."""
    description: str | None = None
    provision_ids: set[str] = field(default_factory=set)
    proposition_ids: set[str] = field(default_factory=set)
    evidence_refs: set[str] = field(default_factory=set)
    mentions: list[Span] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)

    def add_surface(self, surface: str, *, preferred: bool = False) -> None:
        cleaned = _WS_RE.sub(" ", surface).strip()
        if not cleaned:
            return
        self.surfaces[cleaned] = self.surfaces.get(cleaned, 0) + 1
        if preferred and self.preferred is None:
            self.preferred = cleaned

    @property
    def label(self) -> str:
        if not self.surfaces:
            return self.key
        return min(
            self.surfaces,
            key=lambda s: (-self.surfaces[s], s != self.preferred, s),
        )

    @property
    def aliases(self) -> list[str]:
        return sorted(s for s in self.surfaces if s != self.label)


class _GraphBuilder:
    """Assembles nodes and edges, keeping every relation attached to its evidence."""

    def __init__(self, document: DocumentModel, propositions: Sequence[Proposition]) -> None:
        self.document = document
        self.propositions = list(propositions)
        self.resolver = build_entity_resolver(document)
        self._drafts: dict[str, _NodeDraft] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._by_provision: dict[str, list[Proposition]] = defaultdict(list)
        for proposition in self.propositions:
            if proposition.derived_from_provision_id:
                self._by_provision[proposition.derived_from_provision_id].append(proposition)
        self.unmatched_assumptions: list[str] = []

    # -- node bookkeeping ---------------------------------------------------

    def node(
        self,
        kind: NodeKind,
        label: str,
        *,
        description: str | None = None,
        provision_ids: Iterable[str] = (),
        span: Span | None = None,
        attributes: Mapping[str, str] | None = None,
        key_override: str | None = None,
    ) -> str | None:
        """Register a surface form under its canonical entity, returning its node id.

        Returns ``None`` when the label carries nothing that survives folding.
        An entity with no resolvable name is dropped rather than given a blank
        key, because a blank key would silently collect every such entity into
        one node and assert that they are the same thing.
        """
        key = key_override or self.resolver.key(label)
        if not key:
            return None
        identifier = node_id(key, kind=kind.value)
        draft = self._drafts.get(identifier)
        if draft is None:
            draft = _NodeDraft(key=key, kind=kind)
            self._drafts[identifier] = draft
        stem, parenthetical = self.resolver.strip_parentheticals(label)
        # The stem is registered as the preferred form: a document that writes
        # "Long Name (LN)" is introducing the long name, and a reader looking at
        # the graph should see it rather than the bracketed short form.
        draft.add_surface(stem or label, preferred=True)
        draft.add_surface(label)
        for alias in parenthetical:
            draft.add_surface(alias)
        if description and not draft.description:
            draft.description = description
        draft.provision_ids.update(pid for pid in provision_ids if pid.startswith("prov:"))
        if span is not None:
            draft.mentions.append(span)
        for attr_key, attr_value in (attributes or {}).items():
            draft.attributes.setdefault(attr_key, attr_value)
        return identifier

    def edge(
        self,
        source: str | None,
        kind: EdgeKind,
        target: str | None,
        *,
        basis: EdgeBasis,
        evidence_refs: Iterable[str],
        direction: Direction | None = None,
        magnitude: Magnitude | None = None,
        mechanism: str | None = None,
        causality: Causality | None = None,
        time_horizon: TimeHorizon | None = None,
        conditions: Iterable[str] = (),
        label: str | None = None,
        money: object | None = None,
        quantity: object | None = None,
        note: str | None = None,
    ) -> str | None:
        """Register a relation, merging evidence when the same relation recurs.

        The same claim asserted by three provisions is one edge with three
        evidence references, not three edges: an interface that counted them
        separately would present repetition as corroboration.
        """
        if source is None or target is None or source == target:
            return None
        identifier = edge_id(source, kind.value, target)
        refs = sorted({r for r in evidence_refs if r})
        existing = self._edges.get(identifier)
        if existing is not None:
            merged = sorted(set(existing.evidence_refs) | set(refs))
            self._edges[identifier] = existing.model_copy(
                update={
                    "evidence_refs": merged,
                    "conditions": sorted(set(existing.conditions) | set(conditions)),
                    "confidence": _edge_confidence(existing.basis or basis, len(merged)),
                }
            )
            return identifier

        self._edges[identifier] = GraphEdge(
            id=identifier,
            kind=kind,
            source=source,
            target=target,
            label=label,
            basis=basis,
            direction=direction,
            magnitude=magnitude if direction not in (None, Direction.NONE) else None,
            time_horizon=time_horizon,
            causality=causality,
            mechanism=mechanism,
            quantity=quantity,  # type: ignore[arg-type]
            money=money,  # type: ignore[arg-type]
            conditions=sorted(set(conditions)),
            evidence_refs=refs,
            provenance=Provenance(
                source_id=self.document.id,
                source_kind=ProvenanceSourceKind.DOCUMENT,
                url=self.document.source.url,
                extractor=f"aleph.propositions.graph@{GRAPH_BUILDER_VERSION}",
            ),
            confidence=_edge_confidence(basis, len(refs)),
            note=note,
        )
        return identifier

    # -- build --------------------------------------------------------------

    def build(self, *, generated_at: str | None) -> TopicGraph:
        document = self.document
        policy = self.node(
            NodeKind.POLICY,
            document.identity.short_title or document.identity.title,
            description=document.identity.summary,
            attributes={
                "document_type": document.identity.document_type,
                "status": document.identity.status.value,
            },
        )
        if policy is not None:
            draft = self._drafts[policy]
            # Every provision belongs to the instrument, so the policy node's
            # salience is by construction the maximum: it is what the document is.
            draft.provision_ids.update(p.id for p in document.provisions)
            for alias in (
                document.identity.title,
                document.identity.subtitle,
                document.identity.short_title,
                document.identity.legislative_identifier,
            ):
                if alias:
                    draft.add_surface(alias)
            for identifier in document.identity.identifiers:
                draft.add_surface(identifier.value)

        party_edges: dict[tuple[EdgeKind, str], set[str]] = defaultdict(set)
        party_directions: dict[tuple[EdgeKind, str], set[Direction]] = defaultdict(set)

        for provision in sorted(document.provisions, key=lambda p: p.id):
            self._provision_subgraph(provision, policy, party_edges, party_directions)

        self._document_level_parties(policy, party_edges, party_directions)
        self._fiscal_effects()
        self._external_instruments()
        self._assumption_edges(policy)
        self._aggregate_policy_edges(policy, party_edges, party_directions)
        self._attach_propositions()

        nodes = self._finalise_nodes()
        edges = sorted(self._edges.values(), key=lambda e: e.id)
        edges = [e for e in edges if _both_endpoints_present(e, {n.id for n in nodes})]

        notes = [
            "Edges marked 'document_implicit' are Aleph's reading of what the document's "
            "own terms entail; edges marked 'document_explicit' restate what it says.",
        ]
        if self.unmatched_assumptions:
            notes.append(
                f"{len(self.unmatched_assumptions)} stated assumption(s) named no entity "
                "already in the graph and are recorded in the document model only."
            )

        return TopicGraph(
            schema_version=SCHEMA_VERSION,
            data_status=document.data_status or DataStatus.DERIVED,
            document_id=document.id,
            generated_at=generated_at,
            nodes=nodes,
            edges=edges,
            stats=_stats(nodes, edges),
            notes=" ".join(notes),
        )

    # -- per-provision ------------------------------------------------------

    def _provision_subgraph(
        self,
        provision: Provision,
        policy: str | None,
        party_edges: dict[tuple[EdgeKind, str], set[str]],
        party_directions: dict[tuple[EdgeKind, str], set[Direction]],
    ) -> None:
        proposition_ids = sorted(p.id for p in self._by_provision.get(provision.id, ()))
        refs = [provision.id, *proposition_ids]

        provision_node = self.node(
            NodeKind.PROVISION,
            provision.title or _truncate(provision.text, 70),
            description=provision.mechanism,
            provision_ids=[provision.id],
            span=provision.span,
            attributes={"provision_type": provision.provision_type.value},
            key_override=".".join(id_parts(provision.id)),
        )
        if provision_node is not None:
            self._drafts[provision_node].proposition_ids.update(proposition_ids)
            self._drafts[provision_node].evidence_refs.add(provision.id)

        # The instrument the provision brings into being, when it brings one.
        instrument_kind = PROVISION_INSTRUMENT_KIND.get(provision.provision_type)
        instrument = None
        if instrument_kind is not None:
            instrument = self.node(
                instrument_kind,
                provision.title or _truncate(provision.text, 60),
                description=provision.mechanism,
                provision_ids=[provision.id],
                span=provision.span,
                attributes={"instrument_of": provision.provision_type.value},
            )
            if instrument is not None:
                self._drafts[instrument].proposition_ids.update(proposition_ids)
                self.edge(
                    provision_node,
                    EdgeKind.AFFECTS,
                    instrument,
                    basis=EdgeBasis.DOCUMENT_EXPLICIT,
                    evidence_refs=refs,
                    direction=Direction.NONE,
                    mechanism=provision.mechanism,
                    causality=Causality.DIRECT,
                    label="establishes",
                    conditions=provision.conditions,
                )

        origin = instrument or provision_node
        kind, direction = PROVISION_INCIDENCE.get(provision.provision_type, _DEFAULT_INCIDENCE)

        for label in sorted(set(provision.affected_populations)):
            target = self.node(
                NodeKind.SOCIAL_GROUP, label, provision_ids=[provision.id], span=provision.span
            )
            self._incidence(origin, kind, target, direction, provision, refs)
            if target:
                party_edges[(kind, target)].add(provision.id)
                party_directions[(kind, target)].add(direction)

        for label in sorted(set(provision.affected_industries)):
            target = self.node(
                NodeKind.SECTOR, label, provision_ids=[provision.id], span=provision.span
            )
            self._incidence(origin, kind, target, direction, provision, refs)
            if target:
                party_edges[(kind, target)].add(provision.id)
                party_directions[(kind, target)].add(direction)

        for label in sorted(set(provision.affected_regions)):
            target = self.node(
                NodeKind.REGION, label, provision_ids=[provision.id], span=provision.span
            )
            self._incidence(origin, EdgeKind.AFFECTS, target, Direction.NONE, provision, refs)

        for label in sorted(set(provision.affected_institutions)):
            target = self.node(
                NodeKind.INSTITUTION, label, provision_ids=[provision.id], span=provision.span
            )
            self._incidence(
                provision_node, EdgeKind.REGULATES, target, Direction.NONE, provision, refs
            )

        if provision.implementing_body:
            body = self.node(
                NodeKind.INSTITUTION,
                provision.implementing_body,
                provision_ids=[provision.id],
                span=provision.span,
                attributes={"role_in_document": InstitutionRole.IMPLEMENTING.value},
            )
            self.edge(
                provision_node,
                EdgeKind.REGULATES,
                body,
                basis=EdgeBasis.DOCUMENT_EXPLICIT,
                evidence_refs=refs,
                direction=Direction.NONE,
                mechanism=provision.mechanism,
                causality=Causality.DIRECT,
                label="charges with implementation",
            )

        # Dates the provision's operation turns on.
        for value, note in (
            (provision.effective_date, "effective from"),
            (provision.sunset_date, "ceases to apply"),
        ):
            if not value:
                continue
            date_node = self.node(NodeKind.DATE, value, key_override=slugify(value))
            self.edge(
                provision_node,
                EdgeKind.DEPENDS_ON,
                date_node,
                basis=EdgeBasis.DOCUMENT_EXPLICIT,
                evidence_refs=refs,
                label=note,
                time_horizon=TimeHorizon.UNKNOWN,
            )

        for dependency in sorted(set(provision.depends_on)):
            target = self.node(NodeKind.POLICY, dependency, provision_ids=[provision.id])
            self.edge(
                provision_node,
                EdgeKind.DEPENDS_ON,
                target,
                basis=EdgeBasis.DOCUMENT_EXPLICIT,
                evidence_refs=refs,
                label="depends on",
            )

        for amended in sorted(set(provision.amends)):
            target = self.node(NodeKind.POLICY, amended, provision_ids=[provision.id])
            self.edge(
                provision_node,
                EdgeKind.MODIFIES,
                target,
                basis=EdgeBasis.DOCUMENT_EXPLICIT,
                evidence_refs=refs,
                label="amends",
            )

    def _incidence(
        self,
        origin: str | None,
        kind: EdgeKind,
        target: str | None,
        direction: Direction,
        provision: Provision,
        refs: Sequence[str],
    ) -> None:
        """Record who a provision falls on.

        Marked ``document_implicit``: the document names the group, and that a
        levy's named group is the group that pays it follows from the text's own
        terms rather than from a sentence in it. ``magnitude`` stays ``unknown``
        because the text almost never supports a size, and inventing one would
        turn a structural reading into a fabricated measurement.
        """
        self.edge(
            origin,
            kind,
            target,
            basis=EdgeBasis.DOCUMENT_IMPLICIT,
            evidence_refs=refs,
            direction=direction,
            magnitude=Magnitude.UNKNOWN,
            mechanism=provision.mechanism,
            causality=Causality.DIRECT if provision.mechanism else Causality.UNKNOWN,
            conditions=provision.conditions,
            time_horizon=TimeHorizon.UNKNOWN,
        )

    # -- document-level entities -------------------------------------------

    def _document_level_parties(
        self,
        policy: str | None,
        party_edges: dict[tuple[EdgeKind, str], set[str]],
        party_directions: dict[tuple[EdgeKind, str], set[Direction]],
    ) -> None:
        """Fold in the parties phase 1 catalogued at document level."""
        for institution in sorted(self.document.affected_institutions, key=lambda i: i.id):
            target = self.node(
                NodeKind.INSTITUTION,
                institution.name,
                provision_ids=institution.provision_ids,
                span=institution.span,
                attributes={"role_in_document": institution.role_in_document.value},
            )
            if target is None:
                continue
            kind, direction = _INSTITUTION_EDGE[institution.role_in_document]
            refs = list(institution.provision_ids)
            for provision_id in institution.provision_ids or [self.document.id]:
                origin = self._provision_node_id(provision_id) or policy
                self.edge(
                    origin,
                    kind,
                    target,
                    basis=EdgeBasis.DOCUMENT_EXPLICIT,
                    evidence_refs=refs or [self.document.id],
                    direction=direction,
                    magnitude=Magnitude.UNKNOWN,
                    label=institution.role_in_document.value,
                )
            party_edges[(kind, target)].update(institution.provision_ids)
            party_directions[(kind, target)].add(direction)

        for population in sorted(self.document.affected_populations, key=lambda p: p.id):
            target = self.node(
                NodeKind.SOCIAL_GROUP,
                population.label,
                description=population.definition_criteria,
                provision_ids=population.provision_ids,
                span=population.span,
            )
            if target is not None and population.estimated_size is not None:
                self._drafts[target].attributes.setdefault(
                    "estimated_size", population.estimated_size.raw_text
                )

        for industry in sorted(self.document.affected_industries, key=lambda i: i.id):
            target = self.node(
                NodeKind.SECTOR,
                industry.label,
                provision_ids=industry.provision_ids,
                span=industry.span,
            )
            if target is not None and industry.classification_code:
                self._drafts[target].attributes.setdefault(
                    "classification_code", industry.classification_code
                )

        for authorship in self.document.identity.authorship:
            if authorship.is_personal_name:
                # A personal name must never become a node: the factual path is
                # required to be structurally unable to see individual identity,
                # and a node holding a name would put one in every reference.
                continue
            label = authorship.entity or authorship.role
            self.node(
                NodeKind.PERSON_ROLE if authorship.entity is None else NodeKind.INSTITUTION,
                label,
                span=authorship.span,
                attributes={"authorship_role": authorship.role},
            )

    def _fiscal_effects(self) -> None:
        """One node per monetary role, so several provisions can converge on one budget line."""
        for value in sorted(self.document.monetary_values, key=lambda v: v.id):
            target = self.node(
                NodeKind.FISCAL_EFFECT,
                value.role.value.replace("_", " "),
                provision_ids=[value.provision_id] if value.provision_id else [],
                span=value.span,
                key_override=value.role.value,
            )
            origin = self._provision_node_id(value.provision_id)
            kind = (
                EdgeKind.FUNDS
                if value.role.value in {"allocation", "transfer"}
                else EdgeKind.AFFECTS
            )
            self.edge(
                origin,
                kind,
                target,
                basis=EdgeBasis.DOCUMENT_EXPLICIT,
                evidence_refs=[r for r in (value.provision_id,) if r],
                direction=Direction.POSITIVE if kind is EdgeKind.FUNDS else Direction.UNCERTAIN,
                magnitude=Magnitude.UNKNOWN,
                money=value.money,
                label=value.label,
                note=(
                    "The document presents this figure as an estimate."
                    if value.is_estimate
                    else None
                ),
            )

    def _external_instruments(self) -> None:
        """Instruments this document changes or leans on, as policy nodes."""
        for amendment in sorted(self.document.amendments, key=lambda a: a.id):
            label = amendment.target_title or amendment.target_identifier
            if not label:
                continue
            target = self.node(NodeKind.POLICY, label, span=amendment.span)
            origin = self._provision_node_id(amendment.provision_id)
            kind = (
                EdgeKind.REPLACES
                if amendment.operation.value in {"repeal", "substitute"}
                else EdgeKind.MODIFIES
            )
            self.edge(
                origin,
                kind,
                target,
                basis=EdgeBasis.DOCUMENT_EXPLICIT,
                evidence_refs=[r for r in (amendment.provision_id,) if r],
                label=amendment.operation.value,
            )

        for dependency in sorted(self.document.legal_dependencies, key=lambda d: d.id):
            label = dependency.title or dependency.identifier
            if not label:
                continue
            target = self.node(NodeKind.POLICY, label, span=dependency.span)
            for provision_id in dependency.provision_ids or []:
                self.edge(
                    self._provision_node_id(provision_id),
                    EdgeKind.DEPENDS_ON,
                    target,
                    basis=EdgeBasis.DOCUMENT_EXPLICIT,
                    evidence_refs=[provision_id],
                    label=dependency.dependency_kind.value,
                    note=dependency.note,
                )

    def _assumption_edges(self, policy: str | None) -> None:
        """Link the document to what its projections take for granted.

        ``assumes`` exists because a policy resting on an assumed take-up or
        compliance rate has a load-bearing link that ordinary impact vocabularies
        omit — and that link is usually the first thing to fail. Assumptions that
        name no entity already in the graph are counted in ``notes`` rather than
        given an invented node: fabricating a node to hang an edge on would be
        exactly the overreach the graph exists to prevent.
        """
        candidates: list[tuple[str, str, list[str]]] = [
            (a.id, a.statement, list(a.applies_to_provision_ids))
            for a in sorted(self.document.assumptions, key=lambda a: a.id)
        ]
        candidates.extend(
            (p.id, p.text, [p.derived_from_provision_id] if p.derived_from_provision_id else [])
            for p in sorted(self.propositions, key=lambda p: p.id)
            if p.proposition_type is PropositionType.ASSUMPTION
        )

        alias_index = self._alias_index()
        for source_id, statement, provision_ids in candidates:
            folded = _fold(statement)
            matched = sorted(
                {
                    identifier
                    for alias, identifier in alias_index.items()
                    if len(alias) >= 5 and alias in folded
                }
            )
            if not matched:
                self.unmatched_assumptions.append(source_id)
                continue
            origins = [self._provision_node_id(pid) for pid in provision_ids] or [policy]
            for origin in origins or [policy]:
                for target in matched:
                    self.edge(
                        origin,
                        EdgeKind.ASSUMES,
                        target,
                        basis=EdgeBasis.DOCUMENT_EXPLICIT,
                        evidence_refs=[source_id, *provision_ids],
                        label="assumes",
                        note=_truncate(statement, 160),
                    )

    def _aggregate_policy_edges(
        self,
        policy: str | None,
        party_edges: dict[tuple[EdgeKind, str], set[str]],
        party_directions: dict[tuple[EdgeKind, str], set[Direction]],
    ) -> None:
        """Summarise, at instrument level, what the document as a whole does to whom.

        Marked ``document_implicit`` and carrying every contributing provision as
        evidence, so a reader who doubts the summary can open it and find the
        clauses. Magnitude is read from how many provisions converge, which is a
        statement about the document's structure rather than about the size of an
        effect in the world — hence ``small``/``medium``/``large`` and never a
        number.
        """
        if policy is None:
            return
        for (kind, target), provisions in sorted(
            party_edges.items(), key=lambda item: (item[0][0].value, item[0][1])
        ):
            if not provisions:
                continue
            directions = party_directions.get((kind, target), set())
            direction = (
                next(iter(directions))
                if len(directions) == 1
                else (Direction.MIXED if directions else Direction.UNCERTAIN)
            )
            count = len(provisions)
            magnitude = (
                Magnitude.LARGE
                if count >= 4
                else Magnitude.MEDIUM
                if count >= 2
                else Magnitude.SMALL
            )
            self.edge(
                policy,
                kind,
                target,
                basis=EdgeBasis.DOCUMENT_IMPLICIT,
                evidence_refs=sorted(provisions),
                direction=direction,
                magnitude=magnitude,
                causality=Causality.INDIRECT,
                time_horizon=TimeHorizon.UNKNOWN,
                label=f"{kind.value} (across {count} provision(s))",
                mechanism=(
                    "Aggregated from the provisions listed in evidence_refs; "
                    "magnitude reflects how many provisions converge, not effect size."
                ),
            )

    def _attach_propositions(self) -> None:
        """Give each node the propositions that mention it, for text-level drill-down."""
        alias_index = self._alias_index()
        for proposition in self.propositions:
            folded = _fold(proposition.text)
            for alias, identifier in alias_index.items():
                if len(alias) >= 5 and alias in folded:
                    self._drafts[identifier].proposition_ids.add(proposition.id)

    # -- finalisation -------------------------------------------------------

    def _finalise_nodes(self) -> list[GraphNode]:
        max_weight = max(
            (len(d.provision_ids) + len(d.mentions) for d in self._drafts.values()), default=0
        )
        nodes: list[GraphNode] = []
        for identifier, draft in sorted(self._drafts.items()):
            weight = len(draft.provision_ids) + len(draft.mentions)
            salience = round(weight / max_weight, 3) if max_weight else None
            nodes.append(
                GraphNode(
                    id=identifier,
                    kind=draft.kind,
                    label=draft.label,
                    aliases=draft.aliases,
                    description=draft.description,
                    salience=salience,
                    provision_ids=sorted(draft.provision_ids),
                    proposition_ids=sorted(draft.proposition_ids),
                    evidence_refs=sorted(draft.evidence_refs | draft.provision_ids),
                    mentions=_dedupe_spans(draft.mentions),
                    attributes=[
                        NodeAttribute(key=k, value=v) for k, v in sorted(draft.attributes.items())
                    ],
                    confidence=_node_confidence(draft),
                )
            )
        return nodes

    def _alias_index(self) -> dict[str, str]:
        """Folded surface form → node id, longest form winning a collision."""
        index: dict[str, str] = {}
        for identifier, draft in sorted(self._drafts.items()):
            if draft.kind in {NodeKind.PROVISION, NodeKind.DATE}:
                continue
            for surface in sorted(draft.surfaces):
                folded = _fold(surface).strip()
                if len(folded) >= 5:
                    index.setdefault(folded, identifier)
        return index

    def _provision_node_id(self, provision_id: str | None) -> str | None:
        if not provision_id or not provision_id.startswith("prov:"):
            return None
        candidate = node_id(".".join(id_parts(provision_id)), kind=NodeKind.PROVISION.value)
        return candidate if candidate in self._drafts else None


def build_topic_graph(
    document: DocumentModel,
    propositions: PropositionSet | Sequence[Proposition] | None = None,
    *,
    generated_at: str | None = None,
) -> TopicGraph:
    """Run warm phase 3 over a document and its propositions.

    Args:
        document: The phase-1 reading, which supplies provisions and the parties
            they name.
        propositions: The phase-2 output. Optional — the graph is buildable from
            the document alone — but supplying it is what lets a reader jump from
            an edge to the sentence that produced it.
        generated_at: UTC timestamp. Left ``None`` by default so two runs over the
            same input are byte-identical and diff cleanly.

    Returns:
        A :class:`~aleph.core.models.TopicGraph` with nodes and edges sorted by
        id and every edge carrying ``evidence_refs``, ``basis`` and a confidence.
    """
    if isinstance(propositions, PropositionSet):
        members: Sequence[Proposition] = propositions.propositions
    else:
        members = propositions or ()
    return _GraphBuilder(document, members).build(generated_at=generated_at)


# ---------------------------------------------------------------------------
# Query utilities
#
# The frontend needs three things from a graph: what is next to this, what does
# this provision touch, and what matters most. All three are pure functions with
# total orderings, so a rendered graph is stable between runs.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Neighbour:
    """One step away from a node, with the edge that got there.

    The edge travels with the neighbour because the relation is the interesting
    part: knowing that a provision and a sector are adjacent says nothing until
    you know whether it taxes them, funds them or merely mentions them.
    """

    node_id: str
    edge: GraphEdge
    outgoing: bool


def _index_nodes(graph: TopicGraph) -> dict[str, GraphNode]:
    return {node.id: node for node in graph.nodes}


def neighbours(
    graph: TopicGraph,
    node: str,
    *,
    direction: Literal["out", "in", "both"] = "both",
    kinds: Iterable[EdgeKind] | None = None,
    basis: Iterable[EdgeBasis] | None = None,
) -> list[Neighbour]:
    """Return the nodes one edge away from ``node``, in a stable order.

    Args:
        graph: The graph to walk.
        node: Node id to start from.
        direction: ``out`` follows edges away from the node, ``in`` follows edges
            into it, ``both`` follows either. Direction matters: "A taxes B" and
            "B taxes A" are different claims and an undirected view of the graph
            would conflate them.
        kinds: Restrict to these edge kinds.
        basis: Restrict to these bases — passing ``{EdgeBasis.DOCUMENT_EXPLICIT}``
            gives only what the document actually said.

    Returns:
        Neighbours sorted by ``(edge id, node id)``. Never a set: the order is
        part of the contract, because a UI that re-orders between renders looks
        like it is showing different data.
    """
    kind_filter = set(kinds) if kinds is not None else None
    basis_filter = set(basis) if basis is not None else None
    out: list[Neighbour] = []
    for edge in graph.edges:
        if kind_filter is not None and edge.kind not in kind_filter:
            continue
        if basis_filter is not None and edge.basis not in basis_filter:
            continue
        if direction in {"out", "both"} and edge.source == node:
            out.append(Neighbour(node_id=edge.target, edge=edge, outgoing=True))
        if direction in {"in", "both"} and edge.target == node:
            out.append(Neighbour(node_id=edge.source, edge=edge, outgoing=False))
    return sorted(out, key=lambda n: (n.edge.id, n.node_id))


def subgraph_for_provision(
    graph: TopicGraph,
    provision_id: str,
    *,
    depth: int = 1,
) -> TopicGraph:
    """Everything one provision touches, as a standalone graph.

    This is the view behind "what does this clause actually do": start at the
    provision's own node, walk ``depth`` steps, and return the induced subgraph
    with its stats recomputed. Returning a real :class:`TopicGraph` rather than a
    list of ids means the result can be rendered, exported or re-queried by the
    same code that handles the whole graph.

    An unknown or unrepresented provision yields an empty graph rather than an
    error: a provision from which nothing could be extracted is a normal, and
    reportable, outcome.
    """
    root = node_id(".".join(id_parts(provision_id)), kind=NodeKind.PROVISION.value)
    index = _index_nodes(graph)
    if root not in index:
        return graph.model_copy(update={"nodes": [], "edges": [], "stats": _stats([], [])})

    reached = {root}
    frontier = {root}
    for _ in range(max(0, depth)):
        nxt: set[str] = set()
        for current in frontier:
            for neighbour in neighbours(graph, current):
                if neighbour.node_id not in reached:
                    nxt.add(neighbour.node_id)
        reached |= nxt
        frontier = nxt
        if not frontier:
            break

    nodes = [node for node in graph.nodes if node.id in reached]
    edges = [edge for edge in graph.edges if edge.source in reached and edge.target in reached]
    return graph.model_copy(
        update={
            "nodes": sorted(nodes, key=lambda n: n.id),
            "edges": sorted(edges, key=lambda e: e.id),
            "stats": _stats(nodes, edges),
            "notes": f"Subgraph induced by {provision_id} at depth {depth}.",
        }
    )


@dataclass(frozen=True, slots=True)
class NodeDegree:
    """Edge counts for one node."""

    node_id: str
    in_degree: int
    out_degree: int

    @property
    def degree(self) -> int:
        return self.in_degree + self.out_degree


def degree_table(graph: TopicGraph) -> list[NodeDegree]:
    """Degree of every node, sorted by id.

    Sorted by id rather than by degree so the table is a stable index; ranking is
    :func:`rank_nodes`'s job.
    """
    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, int] = defaultdict(int)
    for edge in graph.edges:
        outgoing[edge.source] += 1
        incoming[edge.target] += 1
    return [
        NodeDegree(node_id=node.id, in_degree=incoming[node.id], out_degree=outgoing[node.id])
        for node in sorted(graph.nodes, key=lambda n: n.id)
    ]


def centrality(
    graph: TopicGraph,
    *,
    damping: float = 0.85,
    iterations: int = 60,
) -> dict[str, float]:
    """PageRank over the directed graph, computed deterministically.

    Degree alone answers "what is mentioned most", which in a policy document is
    usually whichever body has to file the reports. PageRank answers a more
    useful question — what the document's relations *converge on* — because a
    node inherits weight from the nodes pointing at it. That is the ranking a
    reader wants when asking what an instrument is really about.

    Fixed iteration count and a fixed traversal order (node ids, sorted) rather
    than convergence-on-tolerance, so the result is bit-identical between runs
    and between machines. Dangling mass is redistributed uniformly, which keeps
    the vector a probability distribution when the graph has sinks — and policy
    graphs are full of sinks, since dates and fiscal effects point nowhere.
    """
    ids = sorted(node.id for node in graph.nodes)
    if not ids:
        return {}
    count = len(ids)
    rank = dict.fromkeys(ids, 1.0 / count)

    outgoing: dict[str, list[str]] = {identifier: [] for identifier in ids}
    for edge in sorted(graph.edges, key=lambda e: e.id):
        if edge.source in outgoing and edge.target in rank:
            outgoing[edge.source].append(edge.target)

    for _ in range(max(1, iterations)):
        nxt = dict.fromkeys(ids, (1.0 - damping) / count)
        dangling = 0.0
        for identifier in ids:
            targets = outgoing[identifier]
            if not targets:
                dangling += rank[identifier]
                continue
            share = damping * rank[identifier] / len(targets)
            for target in targets:
                nxt[target] += share
        if dangling:
            spread = damping * dangling / count
            for identifier in ids:
                nxt[identifier] += spread
        rank = nxt

    return {identifier: round(rank[identifier], 6) for identifier in ids}


@dataclass(frozen=True, slots=True)
class NodeRanking:
    """One node's place in the graph, with the parts of the score kept separate.

    The components are exposed rather than folded into one number so that a UI
    can say *why* something ranks highly. A composite with no visible parts is
    the sort of number Aleph refuses to publish elsewhere, and there is no reason
    to make an exception for a ranking aid.
    """

    node_id: str
    label: str
    kind: NodeKind
    degree: int
    centrality: float
    evidence_count: int
    score: float


def rank_nodes(
    graph: TopicGraph,
    *,
    kinds: Iterable[NodeKind] | None = None,
    limit: int | None = None,
) -> list[NodeRanking]:
    """Rank nodes by how central they are to the document.

    The score combines normalised PageRank, normalised degree and how much
    document evidence attaches to the node. It ranks *what the document is
    about*; it is emphatically not a measure of importance in the world, and
    nothing downstream may treat a high rank as a reason to believe anything.

    Ties break on node id, so equal scores produce a stable order.
    """
    kind_filter = set(kinds) if kinds is not None else None
    ranks = centrality(graph)
    degrees = {entry.node_id: entry.degree for entry in degree_table(graph)}
    max_rank = max(ranks.values(), default=0.0) or 1.0
    max_degree = max(degrees.values(), default=0) or 1
    evidence = {
        node.id: len(node.provision_ids) + len(node.proposition_ids) for node in graph.nodes
    }
    max_evidence = max(evidence.values(), default=0) or 1

    out: list[NodeRanking] = []
    for node in graph.nodes:
        if kind_filter is not None and node.kind not in kind_filter:
            continue
        rank = ranks.get(node.id, 0.0)
        degree = degrees.get(node.id, 0)
        support = evidence.get(node.id, 0)
        score = (
            0.5 * (rank / max_rank) + 0.3 * (degree / max_degree) + 0.2 * (support / max_evidence)
        )
        out.append(
            NodeRanking(
                node_id=node.id,
                label=node.label,
                kind=node.kind,
                degree=degree,
                centrality=rank,
                evidence_count=support,
                score=round(score, 6),
            )
        )
    out.sort(key=lambda r: (-r.score, r.node_id))
    return out[:limit] if limit is not None else out


def graph_stats(graph: TopicGraph) -> GraphStats:
    """Recompute summary counts for a graph.

    ``inferred_edge_count`` is the figure to read first: a graph that is mostly
    inferred is a hypothesis and an interface is obliged to label it as one.
    """
    return _stats(graph.nodes, graph.edges)


# ---------------------------------------------------------------------------
# Internal detail
# ---------------------------------------------------------------------------


def _stats(nodes: Sequence[GraphNode], edges: Sequence[GraphEdge]) -> GraphStats:
    connected = {edge.source for edge in edges} | {edge.target for edge in edges}
    return GraphStats(
        node_count=len(nodes),
        edge_count=len(edges),
        inferred_edge_count=sum(1 for e in edges if e.basis is EdgeBasis.INFERRED),
        unsupported_edge_count=sum(1 for e in edges if not e.evidence_refs),
        isolated_node_count=sum(1 for n in nodes if n.id not in connected),
    )


def _both_endpoints_present(edge: GraphEdge, node_ids: set[str]) -> bool:
    return edge.source in node_ids and edge.target in node_ids


def _truncate(text: str, limit: int) -> str:
    cleaned = _WS_RE.sub(" ", text).strip()
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def _dedupe_spans(spans: Sequence[Span]) -> list[Span]:
    """Keep one span per (page, offset, text), in a stable order."""
    seen: dict[tuple[int | None, int | None, str], Span] = {}
    for span in spans:
        seen.setdefault((span.page, span.char_start, span.text), span)
    return [
        seen[key]
        for key in sorted(
            seen, key=lambda k: (k[0] is None, k[0] or 0, k[1] is None, k[1] or 0, k[2])
        )
    ]


def _edge_confidence(basis: EdgeBasis | None, evidence_count: int) -> Confidence:
    """Confidence that the relation holds as stated.

    Anchored on ``basis``, because where a relation came from is the dominant
    fact about how much it can be relied on: an explicit statement in the source
    is not the same kind of thing as Aleph's reading of what the source entails,
    and a single number that hid the difference would let the second borrow the
    standing of the first.
    """
    base = {
        EdgeBasis.DOCUMENT_EXPLICIT: 0.9,
        EdgeBasis.DOCUMENT_IMPLICIT: 0.7,
        EdgeBasis.EXTERNAL_EVIDENCE: 0.6,
        EdgeBasis.INFERRED: 0.45,
        None: 0.4,
    }[basis]
    bonus = min(0.08, 0.02 * max(0, evidence_count - 1))
    factors = [
        ConfidenceBasis(
            factor=ConfidenceFactor.PRIMARY_SOURCE_COVERAGE,
            effect=(
                ConfidenceEffect.RAISES
                if basis in {EdgeBasis.DOCUMENT_EXPLICIT, EdgeBasis.DOCUMENT_IMPLICIT}
                else ConfidenceEffect.NEUTRAL
            ),
            note=f"Relation basis: {basis.value if basis else 'unstated'}.",
        )
    ]
    if evidence_count == 0:
        factors.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.PRIMARY_SOURCE_COVERAGE,
                effect=ConfidenceEffect.LOWERS,
                note="No provision or proposition is cited for this relation.",
            )
        )
    elif evidence_count > 1:
        factors.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.EVIDENCE_AGREEMENT,
                effect=ConfidenceEffect.RAISES,
                note=f"{evidence_count} document references support this relation.",
            )
        )
    limiting = (
        "Aleph inferred this relation from the document's terms; the document does not state it."
        if basis is EdgeBasis.DOCUMENT_IMPLICIT
        else ("No supporting reference was recorded." if evidence_count == 0 else None)
    )
    return Confidence(
        evidence_confidence=round(min(1.0, base + bonus if evidence_count else base - 0.15), 3),
        model_confidence=None,
        basis=factors,
        limiting_factor=limiting,
    )


def _node_confidence(draft: _NodeDraft) -> Confidence:
    """Confidence that the entity was correctly identified and resolved.

    Not confidence that it matters. Merging several spellings raises it — the
    same body named repeatedly is unlikely to be a segmentation artefact — while
    a node seen once, with no located mention, is flagged as the weakest kind of
    identification.
    """
    surfaces = len(draft.surfaces)
    score = 0.6 + min(0.3, 0.1 * surfaces) + (0.1 if draft.mentions else 0.0)
    factors = [
        ConfidenceBasis(
            factor=ConfidenceFactor.PRIMARY_SOURCE_COVERAGE,
            effect=ConfidenceEffect.RAISES if draft.mentions else ConfidenceEffect.NEUTRAL,
            note=f"{len(draft.mentions)} located mention(s); {surfaces} surface form(s) merged.",
        )
    ]
    limiting = None
    if surfaces > 1:
        factors.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.CLAIM_AMBIGUITY,
                effect=ConfidenceEffect.LOWERS,
                note="Several surface forms were merged; check the aliases if the identity is disputed.",
            )
        )
        limiting = "Co-reference was resolved by name folding, not by an external register."
    return Confidence(
        evidence_confidence=round(min(1.0, score), 3),
        model_confidence=None,
        basis=factors,
        limiting_factor=limiting,
    )
