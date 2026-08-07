"""Seven-phase orchestration with an evidence-readiness stop.

The local pipeline completes the four document-derived warm phases offline. It
does not pretend retrieval happened: evidence collection and news clustering
are explicitly skipped, and readiness therefore blocks verdicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aleph.core.enums import PhaseState, WarmPhase
from aleph.core.models import DocumentModel, PropositionSet, SearchVocabulary, TopicGraph
from aleph.documents import build_document_model
from aleph.ingestion import extract_pdf, extract_plain_text, load_source
from aleph.propositions.extract import extract_propositions
from aleph.propositions.graph import build_topic_graph
from aleph.retrieval.vocabulary import build_search_vocabulary

PIPELINE_VERSION = "aleph-pipeline/0.1.0"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class PhaseResult:
    phase: WarmPhase
    state: PhaseState
    completed_at: str
    item_count: int | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "state": self.state.value,
            "completed_at": self.completed_at,
            "item_count": self.item_count,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class PipelineReadiness:
    overall_state: str
    overall_score: int
    publishable: bool
    why_not_publishable: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_state": self.overall_state,
            "overall_score": self.overall_score,
            "publishable": self.publishable,
            "why_not_publishable": self.why_not_publishable,
        }


@dataclass(frozen=True, slots=True)
class PipelineResult:
    pipeline_version: str
    generated_at: str
    document: DocumentModel
    propositions: PropositionSet
    topic_graph: TopicGraph
    search_vocabulary: SearchVocabulary
    readiness: PipelineReadiness
    phases: tuple[PhaseResult, ...]

    @property
    def slug(self) -> str:
        return self.document.identity.slug

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_version": self.pipeline_version,
            "generated_at": self.generated_at,
            "document": self.document.to_jsonable(),
            "propositions": self.propositions.to_jsonable(),
            "topic_graph": self.topic_graph.to_jsonable(),
            "search_vocabulary": self.search_vocabulary.to_jsonable(),
            "readiness": self.readiness.to_dict(),
            "phases": [phase.to_dict() for phase in self.phases],
        }


def run_analysis(
    source: bytes | str | Path,
    *,
    title: str | None = None,
    allow_network: bool = False,
    provider: Any | None = None,
) -> PipelineResult:
    """Run the offline-capable warm path and stop honestly at retrieval."""
    fetched = load_source(source, allow_network=allow_network, file_name=title)
    extracted = (
        extract_pdf(fetched.content, source_name=fetched.file_name or fetched.url)
        if fetched.is_pdf
        else extract_plain_text(fetched.content.decode("utf-8"))
    )
    generated_at = _now()
    document = build_document_model(fetched, extracted, title=title)
    propositions = extract_propositions(document, generated_at=generated_at)
    graph = build_topic_graph(document, propositions, generated_at=generated_at)
    vocabulary = build_search_vocabulary(
        document,
        graph=graph,
        provider=provider,
        generated_at=generated_at,
    )
    query_count = sum(
        len(term.generated_queries)
        for field_name in type(vocabulary.term_sets).model_fields
        for term in getattr(vocabulary.term_sets, field_name)
    )
    phases = (
        PhaseResult(
            WarmPhase.DOCUMENT_UNDERSTANDING,
            PhaseState.COMPLETE,
            generated_at,
            len(document.provisions),
        ),
        PhaseResult(
            WarmPhase.PROPOSITION_EXTRACTION,
            PhaseState.COMPLETE,
            generated_at,
            len(propositions.propositions),
        ),
        PhaseResult(WarmPhase.TOPIC_GRAPH, PhaseState.COMPLETE, generated_at, len(graph.nodes)),
        PhaseResult(
            WarmPhase.SEARCH_VOCABULARY,
            PhaseState.COMPLETE,
            generated_at,
            query_count,
        ),
        PhaseResult(
            WarmPhase.EVIDENCE_COLLECTION,
            PhaseState.SKIPPED,
            generated_at,
            0,
            "Network retrieval was not enabled for this run.",
        ),
        PhaseResult(
            WarmPhase.NEWS_CLUSTERING,
            PhaseState.SKIPPED,
            generated_at,
            0,
            "No retrieved coverage was available to cluster.",
        ),
        PhaseResult(
            WarmPhase.READINESS,
            PhaseState.COMPLETE,
            generated_at,
            1,
            "Verdicts are withheld until evidence collection runs.",
        ),
    )
    readiness = PipelineReadiness(
        overall_state="insufficient",
        overall_score=25 if document.provisions else 10,
        publishable=False,
        why_not_publishable=(
            "The document-derived warm phases completed, but no external evidence was retrieved; "
            "speaker-blind verdicts are withheld."
        ),
    )
    return PipelineResult(
        PIPELINE_VERSION,
        generated_at,
        document,
        propositions,
        graph,
        vocabulary,
        readiness,
        phases,
    )
