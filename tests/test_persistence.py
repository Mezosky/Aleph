from __future__ import annotations

from dataclasses import dataclass, replace

from sqlalchemy import func, select

from aleph.core.config import Config, Secret
from aleph.pipeline import run_analysis
from api.database import AnalysisArtifactRow, Database, SourceSnapshotRow
from api.jobs import JobStore


def test_job_store_persists_source_snapshot_and_phase_artifacts() -> None:
    database = Database("sqlite:///:memory:")
    config = replace(Config(), database_url=Secret("sqlite:///:memory:"))
    store = JobStore(config=config, database=database)

    created = store.create(
        b"The agency shall publish a report.", "fixture.txt", allow_network=False
    )
    store.run(created.id)
    completed = store.get(created.id)

    assert completed is not None
    assert completed.state == "complete"
    assert completed.result_sha256
    with database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(SourceSnapshotRow)) == 1
        assert session.scalar(select(func.count()).select_from(AnalysisArtifactRow)) == 6


def test_completed_run_survives_process_store_recreation(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'aleph.db'}"
    config = replace(Config(), database_url=Secret(url))
    first = JobStore(config=config, database=Database(url))
    created = first.create(b"The service keeps an audit log.", "durable.txt", allow_network=False)
    first.run(created.id)
    stored = first.get(created.id)
    assert stored is not None
    expected_hash = stored.result_sha256
    first.database.dispose()

    reopened = JobStore(config=config, database=Database(url))
    recovered = reopened.get(created.id)
    assert recovered is not None
    assert recovered.state == "complete"
    assert recovered.result_sha256 == expected_hash


def test_job_store_rerun_accumulates_without_overwriting() -> None:
    database = Database("sqlite:///:memory:")
    config = replace(Config(), database_url=Secret("sqlite:///:memory:"))
    store = JobStore(config=config, database=database)
    original = store.create(b"A municipality maintains a register.", "one.txt", allow_network=False)
    store.run(original.id)
    original_after = store.get(original.id)

    replacement = store.rerun(original.id)
    assert replacement is not None
    store.run(replacement.id)
    original_final = store.get(original.id)
    replacement_final = store.get(replacement.id)

    assert (
        original_after is not None and original_final is not None and replacement_final is not None
    )
    assert original_final.result_sha256 == original_after.result_sha256
    assert replacement_final.supersedes_run_id == original.id
    assert replacement_final.source_snapshot_id == original_final.source_snapshot_id
    assert len(store.history(original.document_id)) == 2
    with database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(SourceSnapshotRow)) == 1


@dataclass
class _AuditableResponse:
    parsed: dict
    text: str = ""


class _ResponseProvider:
    name = "response-fixture"

    def complete(self, prompt: str, *, schema=None):
        if schema and "propositions" in schema.get("properties", {}):
            return _AuditableResponse(
                {
                    "propositions": [
                        {
                            "text": "The agency must publish a report.",
                            "quote": "The agency must publish a report.",
                            "proposition_type": "obligation",
                        }
                    ]
                }
            )
        return _AuditableResponse(
            {
                "common_names": [],
                "political_terminology": [],
                "synonyms": [],
                "translations": [],
            }
        )


def test_concrete_provider_response_is_used_instead_of_silent_rule_fallback() -> None:
    result = run_analysis(
        b"The agency must publish a report.",
        title="provider.txt",
        provider=_ResponseProvider(),
    )
    assert "response-fixture" in result.propositions.extractor
    assert any(
        item.text == "The agency must publish a report."
        for item in result.propositions.propositions
    )
