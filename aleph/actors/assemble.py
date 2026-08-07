"""Assemble actor profiles after blind claim evaluation has completed."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from aleph.actors.models import ActorProfile, ActorProfileSet
from aleph.actors.track_record import build_claim_track_record
from aleph.core.enums import DataStatus


class ActorProfileAssembler:
    """Merge official-record facts with track records from blind verdicts."""

    def assemble(
        self,
        records: Sequence[ActorProfile | Mapping[str, Any]],
        claims: Iterable[Any],
        *,
        data_status: DataStatus = DataStatus.DERIVED,
        generated_at: datetime | None = None,
    ) -> ActorProfileSet:
        claim_rows = tuple(claims)
        actors: list[ActorProfile] = []
        for record in records:
            profile = (
                record if isinstance(record, ActorProfile) else ActorProfile.model_validate(record)
            )
            profile = profile.model_copy(
                update={"claim_track_record": build_claim_track_record(claim_rows, profile.id)}
            )
            actors.append(profile)
        return ActorProfileSet(
            data_status=data_status,
            generated_at=generated_at or datetime.now(UTC),
            actors=tuple(actors),
        )


def assemble_profiles(
    records: Sequence[ActorProfile | Mapping[str, Any]], claims: Iterable[Any]
) -> ActorProfileSet:
    return ActorProfileAssembler().assemble(records, claims)
