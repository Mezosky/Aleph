from __future__ import annotations

import pytest
from pydantic import ValidationError

from aleph.actors import ActorProfile, LegalRecordEntry, SourceRef, build_claim_track_record
from aleph.claims.evaluate import evaluate_blind
from aleph.core.enums import EvidenceTier
from aleph.core.errors import NeutralityViolationError


def official_source() -> SourceRef:
    return SourceRef(
        id="src:test-court",
        title="Official ruling",
        url="https://court.example/ruling/1",
        tier=EvidenceTier.PRIMARY_DOCUMENT,
    )


def test_unresolved_legal_record_requires_presumption_note() -> None:
    with pytest.raises(ValidationError, match="presumption note"):
        LegalRecordEntry(
            summary="A proceeding remains open.",
            status="charged",
            resolved=False,
            body="Test court",
            presumption_note=None,
            source=official_source(),
        )


def test_organisation_cannot_have_personal_legal_record() -> None:
    record = LegalRecordEntry(
        summary="The proceeding ended in dismissal.",
        status="dismissed",
        resolved=True,
        body="Test court",
        presumption_note=None,
        source=official_source(),
    )
    with pytest.raises(ValidationError, match="organisations"):
        ActorProfile(
            id="actor:test-body",
            display_name="Test body",
            is_natural_person=False,
            roles=(),
            legal_record=(record,),
            sources=(official_source(),),
        )


def test_track_record_reads_only_blind_verdicts_for_actor() -> None:
    claims = [
        {
            "id": "clm:1",
            "made_at": "2026-01-01",
            "statement_type": "fact",
            "blind_evaluation": {"verdict": "supported"},
            "attributed_analysis": {
                "applied_after_verdict": True,
                "speaker_id": "actor:test",
            },
        },
        {
            "id": "clm:2",
            "made_at": "2026-02-01",
            "statement_type": "forecast",
            "blind_evaluation": {"verdict": "forecast_conditional"},
            "attributed_analysis": {
                "applied_after_verdict": True,
                "speaker_id": "actor:test",
            },
        },
    ]
    record = build_claim_track_record(claims, "actor:test")
    assert record.sample_size == 2
    assert record.by_verdict == {"supported": 1, "forecast_conditional": 1}
    assert record.evaluated_claim_ids == ("clm:1", "clm:2")


def test_actor_profile_is_blocked_from_blind_path() -> None:
    with pytest.raises(NeutralityViolationError, match="attributed data was blocked"):
        evaluate_blind({"actors": []})  # type: ignore[arg-type]
