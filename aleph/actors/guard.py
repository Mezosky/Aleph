"""Runtime tripwire protecting the blind evaluation boundary."""

from __future__ import annotations

from typing import Any

from aleph.core.errors import NeutralityViolationError
from aleph.core.models import RedactedClaimContext


def assert_blind_input(value: Any) -> RedactedClaimContext:
    """Return a valid blind context or raise before evaluation starts.

    Static typing catches ordinary misuse.  This guard covers dynamic callers,
    API payloads and future refactors: an actor profile receives an explicit
    neutrality error instead of failing later through incidental attribute use.
    """
    if not isinstance(value, RedactedClaimContext):
        name = type(value).__name__
        actor_like = name in {"ActorProfile", "ActorProfileSet"} or (
            isinstance(value, dict)
            and ("actors" in value or "claim_track_record" in value or "legal_record" in value)
        )
        detail = "actor profile" if actor_like else name
        raise NeutralityViolationError(
            "blind evaluation accepts only RedactedClaimContext; attributed data was blocked",
            stage="blind_evaluation",
            leaked_category=detail,
        )
    return value
