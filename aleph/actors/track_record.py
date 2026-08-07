"""Aggregate only Aleph's own speaker-blind verdicts by attributed actor."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from aleph.actors.models import ClaimTrackRecord

TRACK_RECORD_CAVEAT = (
    "Muestra pequeña y no aleatoria: incluye sólo afirmaciones que Aleph analizó a ciegas. "
    "No representa toda la trayectoria del actor ni predice la veracidad de una afirmación futura."
)


def _value(item: Any, *path: str) -> Any:
    current = item
    for key in path:
        current = current.get(key) if isinstance(current, dict) else getattr(current, key, None)
        if current is None:
            return None
    return current.value if hasattr(current, "value") else current


def build_claim_track_record(claims: Iterable[Any], actor_id: str) -> ClaimTrackRecord:
    """Build an auditable, non-predictive history for one actor.

    A claim is included only when attribution happened after the verdict and its
    ``speaker_id`` matches.  The verdict is always read from
    ``blind_evaluation.verdict``; there is no attributed verdict to consult.
    """
    selected: list[Any] = []
    for claim in claims:
        if _value(claim, "attributed_analysis", "applied_after_verdict") is not True:
            continue
        if _value(claim, "attributed_analysis", "speaker_id") == actor_id:
            selected.append(claim)

    verdicts = Counter(str(_value(claim, "blind_evaluation", "verdict")) for claim in selected)
    statement_types = Counter(str(_value(claim, "statement_type")) for claim in selected)
    claim_ids = tuple(str(_value(claim, "id")) for claim in selected)
    dates = [_value(claim, "made_at") for claim in selected]
    parsed_dates: list[date] = []
    for value in dates:
        if isinstance(value, datetime):
            parsed_dates.append(value.date())
        elif isinstance(value, date):
            parsed_dates.append(value)
        elif isinstance(value, str):
            parsed_dates.append(date.fromisoformat(value[:10]))

    period = None
    if parsed_dates:
        period = {"from": min(parsed_dates), "to": max(parsed_dates)}

    return ClaimTrackRecord(
        sample_size=len(selected),
        by_verdict=dict(verdicts),
        by_statement_type=dict(statement_types),
        evaluated_claim_ids=claim_ids,
        period=period,
        caveat=TRACK_RECORD_CAVEAT,
    )
