"""Attributed-stage actor profiles assembled from auditable records.

Profiles are context, never evidence for a verdict.  The public functions in
this package deliberately live outside ``aleph.claims`` so the dependency can
only point from the attributed stage toward profiles, never from profiles into
the blind evaluator.
"""

from aleph.actors.assemble import ActorProfileAssembler, assemble_profiles
from aleph.actors.guard import assert_blind_input
from aleph.actors.models import (
    ActorProfile,
    ActorProfileSet,
    Affiliation,
    ClaimTrackRecord,
    DeclaredInterest,
    FramingPattern,
    LegalRecordEntry,
    Role,
    SourceRef,
)
from aleph.actors.track_record import build_claim_track_record

__all__ = [
    "ActorProfile",
    "ActorProfileAssembler",
    "ActorProfileSet",
    "Affiliation",
    "ClaimTrackRecord",
    "DeclaredInterest",
    "FramingPattern",
    "LegalRecordEntry",
    "Role",
    "SourceRef",
    "assemble_profiles",
    "assert_blind_input",
    "build_claim_track_record",
]
