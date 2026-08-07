"""Where retrieved evidence is kept, and what keeping it does and does not mean.

An evidence store is a plain enough thing — put items in, get them out — but two
of its decisions are epistemic rather than technical, and getting either wrong
corrupts everything downstream.

**Presence is not endorsement.** An item is recorded because it was found, not
because it is good. Items are kept here precisely when they are weak,
contradicted or off-point, because a store that quietly dropped inconvenient
material would produce an evidence base shaped by the pipeline's expectations
rather than by what exists. Nothing in this module ranks, filters by quality or
scores an item; that judgement belongs to :mod:`aleph.evidence.rank`, is made
against a *specific question*, and is recomputed rather than stored.

**Deduplication must not eat corroboration.** The same statement retrieved twice
from one source is one piece of evidence and should merge. The same statement
obtained from two *different* sources is two pieces of evidence and must not.
That distinction is the whole design of :func:`evidence_fingerprint`, which
includes source identity in the key for exactly this reason: a dedup rule that
keyed on statement text alone would silently collapse genuine corroboration into
a single item, and Aleph would then under-report how much is actually known —
the mirror image of the syndication error, and just as wrong.

The interface is an ABC with two implementations, in-memory and JSON-file-backed,
so a pipeline run, an API process and a test can share one contract. Iteration is
in insertion order and stable across a save/load round trip, because an evidence
set's member order is part of a published bundle and must diff cleanly. Order
must never affect a verdict either — the ``evidence_order_shuffle`` perturbation
exists to test exactly that — so stability here is about reproducibility, not
about privileging whatever arrived first.

Nothing in this module touches the network.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from aleph.core.enums import DataStatus, EvidenceTier
from aleph.core.errors import SchemaMismatchError
from aleph.core.ids import stable_hash, validate_id
from aleph.core.models import (
    SCHEMA_VERSION,
    EvidenceItem,
    EvidencePool,
    EvidenceSet,
    RetrievalGap,
    Span,
)

__all__ = [
    "AddOutcome",
    "AddResult",
    "DedupPolicy",
    "EvidenceStore",
    "InMemoryEvidenceStore",
    "JsonFileEvidenceStore",
    "evidence_fingerprint",
]

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-z]+(?:[.,][0-9]+)*")
_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Fold text for comparison: accents stripped, case dropped, spaces collapsed."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WS_RE.sub(" ", stripped.lower()).strip()


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(_normalise(text))


class DedupPolicy(StrEnum):
    """What to do when an incoming item is already present.

    ``merge`` is the default because a second retrieval of the same passage
    usually carries something the first did not — an extra span, another claim it
    bears on — and discarding it loses information while keeping it twice would
    inflate every count that reads the store.
    """

    MERGE = "merge"
    SKIP = "skip"
    REJECT = "reject"
    """Raise. For pipelines that treat a duplicate as a bug in the caller."""


class AddOutcome(StrEnum):
    """What actually happened to an item on insert."""

    INSERTED = "inserted"
    MERGED = "merged"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class AddResult:
    """The result of one insert, reported rather than inferred.

    Callers need to know whether an addition increased the size of the evidence
    base or merely confirmed something already in it, because only the first can
    change what is known.
    """

    id: str
    outcome: AddOutcome
    fingerprint: str
    merged_into: str | None = None

    @property
    def is_new(self) -> bool:
        return self.outcome is AddOutcome.INSERTED


def evidence_fingerprint(item: EvidenceItem) -> str:
    """A content key for deduplication, deliberately including source identity.

    The key is built from the normalised statement, the source's identity (its
    URL where it has one, otherwise its registry id) and the normalised text of
    every span. Source identity is in the key on purpose, and it is the most
    important thing about this function: without it, the same finding reported
    independently by two sources would collapse to one item, and Aleph would
    understate corroboration in exactly the way it works hardest to avoid
    overstating it.

    Spans are included because two passages of one document can support different
    statements, and because a differing span means a different piece of the
    source is being relied on.
    """
    source_identity = item.source_ref.url or item.source_ref.id
    span_key = "|".join(sorted(_normalise(s.text) for s in item.spans))
    return stable_hash(
        _normalise(item.statement),
        _normalise(source_identity),
        item.tier.value,
        span_key,
        length=24,
    )


def _merge_items(existing: EvidenceItem, incoming: EvidenceItem) -> EvidenceItem:
    """Fold a duplicate into the item already held, losing nothing.

    Unions the claim references, spans, quantities, money and uncertainties. The
    existing id and first-retrieval time are kept so that a reference published in
    an earlier bundle still resolves, and the merge is written into ``notes`` so
    that "this item was seen twice" remains an inspectable fact rather than
    becoming invisible.

    Nothing here can turn two items into more evidence than either was: the merge
    only ever happens between items that :func:`evidence_fingerprint` says are the
    same passage from the same source.
    """

    def union(left: Sequence[str], right: Sequence[str]) -> list[str]:
        return sorted({*left, *right})

    spans: list[Span] = list(existing.spans)
    seen = {_normalise(s.text) for s in spans}
    for span in incoming.spans:
        key = _normalise(span.text)
        if key not in seen:
            seen.add(key)
            spans.append(span)

    note = (
        f"seen again at {incoming.retrieved_at}"
        if incoming.retrieved_at != existing.retrieved_at
        else "duplicate retrieval merged"
    )
    notes = f"{existing.notes}; {note}" if existing.notes else note

    return existing.model_copy(
        update={
            "supports": union(existing.supports, incoming.supports),
            "contradicts": union(existing.contradicts, incoming.contradicts),
            "spans": spans,
            "quantities": [*existing.quantities, *incoming.quantities],
            "money": [*existing.money, *incoming.money],
            "uncertainties": [*existing.uncertainties, *incoming.uncertainties],
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class EvidenceStore(ABC):
    """The contract every evidence store satisfies.

    Deliberately narrow. There is no ``score``, no ``rank`` and no ``best_for``:
    a store answers "what have we got" and never "what is worth believing",
    because the second question has no answer independent of the question being
    asked. :func:`aleph.evidence.rank.rank_evidence` answers it, per question,
    and does not persist the result.
    """

    def __init__(
        self,
        *,
        dedup: DedupPolicy = DedupPolicy.MERGE,
        data_status: DataStatus = DataStatus.DERIVED,
        generated_at: str | None = None,
        document_id: str | None = None,
    ) -> None:
        self.dedup = dedup
        self.data_status = data_status
        self.document_id = document_id
        self._generated_at = generated_at

    # -- required ------------------------------------------------------------

    @abstractmethod
    def add(self, item: EvidenceItem) -> AddResult:
        """Insert an item, applying the dedup policy. Returns what happened."""

    @abstractmethod
    def get(self, evidence_id: str) -> EvidenceItem | None: ...

    @abstractmethod
    def remove(self, evidence_id: str) -> bool: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    def __iter__(self) -> Iterator[EvidenceItem]: ...

    @abstractmethod
    def __len__(self) -> int: ...

    # -- provided ------------------------------------------------------------

    def add_many(self, items: Iterable[EvidenceItem]) -> tuple[AddResult, ...]:
        """Insert several items in order, returning one result each."""
        return tuple(self.add(item) for item in items)

    def require(self, evidence_id: str) -> EvidenceItem:
        item = self.get(evidence_id)
        if item is None:
            raise KeyError(f"no evidence item {evidence_id!r} in store")
        return item

    def __contains__(self, evidence_id: object) -> bool:
        return isinstance(evidence_id, str) and self.get(evidence_id) is not None

    def all(self) -> tuple[EvidenceItem, ...]:
        """Every item, in insertion order."""
        return tuple(self)

    def by_claim(self, claim_id: str, *, relation: str | None = None) -> tuple[EvidenceItem, ...]:
        """Items bearing on one claim, supporting and contradicting alike.

        Both directions are returned by default, and that is not a convenience.
        A caller that had to ask separately for contradicting evidence would
        eventually forget to, and an evaluation that sees only supporting items is
        not an evaluation.

        Args:
            claim_id: The claim.
            relation: ``'supports'``, ``'contradicts'``, or ``None`` for both.
        """
        if relation not in (None, "supports", "contradicts"):
            raise ValueError(
                f"relation must be 'supports', 'contradicts' or None, got {relation!r}"
            )
        out: list[EvidenceItem] = []
        for item in self:
            supports = claim_id in item.supports
            contradicts = claim_id in item.contradicts
            if relation == "supports" and supports:
                out.append(item)
            elif relation == "contradicts" and contradicts:
                out.append(item)
            elif relation is None and (supports or contradicts):
                out.append(item)
        return tuple(out)

    def by_tier(self, *tiers: EvidenceTier) -> tuple[EvidenceItem, ...]:
        """Items of the given artefact classes.

        A filter on what kind of thing an item is, never a filter on quality.
        Selecting only ``primary_document`` narrows what questions the resulting
        set can answer; it does not improve it.
        """
        wanted = set(tiers)
        return tuple(item for item in self if item.tier in wanted)

    def by_source(self, source_id: str) -> tuple[EvidenceItem, ...]:
        """Items drawn from one registered source."""
        return tuple(item for item in self if item.source_ref.id == source_id)

    def by_question(self, question: str, *, exact: bool = False) -> tuple[EvidenceItem, ...]:
        """Items whose recorded relevance was assessed against this question.

        With ``exact=False`` the match is on normalised text, so trailing
        punctuation and casing do not fragment a question into several.
        """
        needle = _normalise(question)
        return tuple(
            item
            for item in self
            if (
                item.evidential_relevance.question == question
                if exact
                else _normalise(item.evidential_relevance.question) == needle
            )
        )

    def search(
        self,
        query: str,
        *,
        tiers: Sequence[EvidenceTier] | None = None,
        limit: int | None = None,
    ) -> tuple[tuple[EvidenceItem, float], ...]:
        """Find items lexically related to a query, with their match scores.

        Retrieval only: an IDF-weighted token overlap over statements, span text
        and recorded questions. It is emphatically *not* a ranking of evidential
        worth — a highly matching item may be an opinion column that establishes
        nothing about the question. Use :func:`aleph.evidence.rank.rank_evidence`
        to decide what an item is worth for a question; use this to find
        candidates to pass to it.

        Ties break on a content hash rather than on the item id, so no ordering
        can be traced back to which source an item came from.
        """
        query_tokens = set(_tokens(query))
        if not query_tokens:
            return ()

        items = [item for item in self if tiers is None or item.tier in set(tiers)]
        if not items:
            return ()

        document_frequency: dict[str, int] = {}
        item_tokens: list[set[str]] = []
        for item in items:
            text = " ".join(
                [item.statement, item.evidential_relevance.question, *(s.text for s in item.spans)]
            )
            tokens = set(_tokens(text))
            item_tokens.append(tokens)
            for token in tokens:
                document_frequency[token] = document_frequency.get(token, 0) + 1

        total = len(items)
        scored: list[tuple[float, str, EvidenceItem]] = []
        for item, tokens in zip(items, item_tokens, strict=True):
            overlap = query_tokens & tokens
            if not overlap:
                continue
            score = sum(
                1.0 / (1.0 + document_frequency.get(token, 0) / total) for token in overlap
            ) / len(query_tokens)
            scored.append((score, stable_hash(_normalise(item.statement), length=16), item))

        scored.sort(key=lambda entry: (-entry[0], entry[1]))
        result = tuple((item, round(score, 4)) for score, _, item in scored)
        return result[:limit] if limit else result

    def stats(self) -> dict[str, Any]:
        """Counts by tier and by independence, plus distinct source count.

        ``distinct_sources`` is the number to read next to ``total``: a store of
        forty items from three sources is a much thinner evidence base than the
        item count suggests, and the two numbers side by side say so.
        """
        by_tier: dict[str, int] = {}
        by_independence: dict[str, int] = {}
        for item in self:
            by_tier[item.tier.value] = by_tier.get(item.tier.value, 0) + 1
            key = item.independence.value if item.independence else "unrecorded"
            by_independence[key] = by_independence.get(key, 0) + 1
        return {
            "total": len(self),
            "distinct_sources": len({item.source_ref.id for item in self}),
            "derived_items": sum(1 for item in self if item.derived_from_evidence_id),
            "by_tier": dict(sorted(by_tier.items())),
            "by_independence": dict(sorted(by_independence.items())),
        }

    def generated_at(self) -> str:
        """Serialisation timestamp, captured once and then held stable.

        A store that stamped a new time on every save would make two identical
        bundles differ, which turns a diff meant to show what changed in the
        analysis into noise. Callers wanting a specific value pass it to the
        constructor.
        """
        if self._generated_at is None:
            self._generated_at = (
                datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            )
        return self._generated_at

    def to_pool(
        self,
        *,
        evidence_sets: Sequence[EvidenceSet] = (),
        retrieval_gaps: Sequence[RetrievalGap] = (),
    ) -> EvidencePool:
        """Render the store as the published contract object.

        ``retrieval_gaps`` is a parameter rather than a stored field because a gap
        is a fact about a *search*, not about the store. It is accepted here so
        that a pool is never published without somewhere to put the failures: a
        reader distinguishes a thin evidence base from a thorough one by what the
        pipeline says it looked for and did not find.
        """
        return EvidencePool(
            schema_version=SCHEMA_VERSION,
            data_status=self.data_status,
            generated_at=self.generated_at(),
            document_id=self.document_id,
            evidence=list(self),
            evidence_sets=list(evidence_sets),
            retrieval_gaps=list(retrieval_gaps),
        )

    def to_json(self, *, indent: int | None = 2) -> str:
        return self.to_pool().to_json(indent=indent)


# ---------------------------------------------------------------------------
# In-memory
# ---------------------------------------------------------------------------


class InMemoryEvidenceStore(EvidenceStore):
    """The reference implementation. Insertion-ordered, deduplicating, offline."""

    def __init__(
        self,
        items: Iterable[EvidenceItem] = (),
        *,
        dedup: DedupPolicy = DedupPolicy.MERGE,
        data_status: DataStatus = DataStatus.DERIVED,
        generated_at: str | None = None,
        document_id: str | None = None,
    ) -> None:
        super().__init__(
            dedup=dedup,
            data_status=data_status,
            generated_at=generated_at,
            document_id=document_id,
        )
        self._items: dict[str, EvidenceItem] = {}
        self._order: list[str] = []
        self._by_fingerprint: dict[str, str] = {}
        for item in items:
            self.add(item)

    def add(self, item: EvidenceItem) -> AddResult:
        """Insert, merge or skip according to the dedup policy.

        Raises:
            ValueError: If the id is malformed or is already in use by a
                *different* item. A silent id collision would make one piece of
                evidence unreachable while every reference to it still resolved to
                the other — the worst possible failure for an audit trail.
        """
        validate_id(item.id, expected_prefix="ev")
        fingerprint = evidence_fingerprint(item)

        existing_id = self._by_fingerprint.get(fingerprint)
        if existing_id is not None:
            if self.dedup is DedupPolicy.REJECT:
                raise ValueError(
                    f"evidence {item.id!r} duplicates {existing_id!r} (same statement, same "
                    f"source, same spans) and the store's dedup policy is 'reject'"
                )
            if self.dedup is DedupPolicy.SKIP:
                return AddResult(
                    id=existing_id,
                    outcome=AddOutcome.SKIPPED,
                    fingerprint=fingerprint,
                    merged_into=existing_id,
                )
            self._items[existing_id] = _merge_items(self._items[existing_id], item)
            return AddResult(
                id=existing_id,
                outcome=AddOutcome.MERGED,
                fingerprint=fingerprint,
                merged_into=existing_id,
            )

        if item.id in self._items:
            raise ValueError(
                f"evidence id {item.id!r} is already in use by a different item "
                f"(fingerprints {evidence_fingerprint(self._items[item.id])} vs {fingerprint}); "
                "ids must be unique or the reference in a published verdict resolves to the "
                "wrong passage"
            )

        self._items[item.id] = item
        self._order.append(item.id)
        self._by_fingerprint[fingerprint] = item.id
        return AddResult(id=item.id, outcome=AddOutcome.INSERTED, fingerprint=fingerprint)

    def get(self, evidence_id: str) -> EvidenceItem | None:
        return self._items.get(evidence_id)

    def remove(self, evidence_id: str) -> bool:
        item = self._items.pop(evidence_id, None)
        if item is None:
            return False
        self._order.remove(evidence_id)
        self._by_fingerprint = {
            key: value for key, value in self._by_fingerprint.items() if value != evidence_id
        }
        return True

    def clear(self) -> None:
        self._items.clear()
        self._order.clear()
        self._by_fingerprint.clear()

    def __iter__(self) -> Iterator[EvidenceItem]:
        for evidence_id in list(self._order):
            item = self._items.get(evidence_id)
            if item is not None:
                yield item

    def __len__(self) -> int:
        return len(self._items)


# ---------------------------------------------------------------------------
# JSON file
# ---------------------------------------------------------------------------


class JsonFileEvidenceStore(InMemoryEvidenceStore):
    """An evidence store persisted as one ``evidence.json``-shaped file.

    Written atomically — temp file then :func:`os.replace` — so an interrupted
    save leaves the previous pool intact rather than a truncated one. A half-
    written evidence file is worse than none: it would load, look plausible, and
    silently narrow what every later phase saw.

    Insertion order survives the round trip, so a store saved and reloaded
    produces a byte-identical pool.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        autosave: bool = True,
        dedup: DedupPolicy = DedupPolicy.MERGE,
        data_status: DataStatus = DataStatus.DERIVED,
        generated_at: str | None = None,
        document_id: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.autosave = False  # suppressed until the initial load completes
        super().__init__(
            dedup=dedup,
            data_status=data_status,
            generated_at=generated_at,
            document_id=document_id,
        )
        if self.path.is_file():
            self.load()
        self.autosave = autosave

    def load(self) -> int:
        """Replace the store's contents with the file's. Returns the item count.

        Raises:
            SchemaMismatchError: If the file is not a valid evidence pool. Loading
                a malformed pool as an empty one would turn a corrupted file into
                a confident analysis of nothing.
        """
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SchemaMismatchError(
                f"evidence store at {self.path} could not be read: {exc}",
                schema_name="evidence",
            ) from exc
        try:
            pool = EvidencePool(**raw)
        except Exception as exc:  # noqa: BLE001 - re-raised as a contract error
            raise SchemaMismatchError(
                f"evidence store at {self.path} is not a valid evidence pool: {exc}",
                schema_name="evidence",
            ) from exc

        previous_autosave = self.autosave
        self.autosave = False
        try:
            self.clear()
            self.data_status = pool.data_status
            self.document_id = pool.document_id
            self._generated_at = pool.generated_at
            for item in pool.evidence:
                self.add(item)
        finally:
            self.autosave = previous_autosave
        return len(self)

    def save(
        self,
        *,
        evidence_sets: Sequence[EvidenceSet] = (),
        retrieval_gaps: Sequence[RetrievalGap] = (),
    ) -> Path:
        """Write the pool atomically and return the path."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_pool(evidence_sets=evidence_sets, retrieval_gaps=retrieval_gaps).to_json()
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temp.write_text(payload + "\n", encoding="utf-8")
        os.replace(temp, self.path)
        return self.path

    # -- mutations write through --------------------------------------------

    def add(self, item: EvidenceItem) -> AddResult:
        result = super().add(item)
        if self.autosave:
            self.save()
        return result

    def remove(self, evidence_id: str) -> bool:
        removed = super().remove(evidence_id)
        if removed and self.autosave:
            self.save()
        return removed

    def clear(self) -> None:
        super().clear()
        if self.autosave:
            self.save()

    def __enter__(self) -> JsonFileEvidenceStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.save()
