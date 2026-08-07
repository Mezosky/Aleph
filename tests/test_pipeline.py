from __future__ import annotations

from aleph.pipeline import run_analysis


def test_pipeline_runs_document_phases_and_refuses_verdicts_without_evidence() -> None:
    result = run_analysis(
        b"The agency shall publish an annual report.\n\nMunicipalities must submit data.",
        title="Fixture.txt",
    )
    assert result.document.identity.title == "Fixture.txt"
    assert result.document.provisions
    assert result.propositions.propositions
    assert result.readiness.publishable is False
    assert result.readiness.overall_state == "insufficient"
    assert [phase.phase.value for phase in result.phases] == [
        "document_understanding",
        "proposition_extraction",
        "topic_graph",
        "search_vocabulary",
        "evidence_collection",
        "news_clustering",
        "readiness",
    ]


def test_pipeline_is_document_agnostic() -> None:
    first = run_analysis(b"A regulator creates a reporting duty.", title="One.txt")
    second = run_analysis(b"A municipality establishes a public register.", title="Two.txt")
    assert first.document.id != second.document.id
    assert first.document.identity.jurisdiction.code is None
    assert second.document.identity.jurisdiction.code is None
