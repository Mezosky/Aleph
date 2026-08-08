"""Apply deterministic identity and affiliation enrichment to the static census."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aleph.dossier.actor_affiliations import enrich_actor_affiliations  # noqa: E402

ACTOR_CENSUS = ROOT / "frontend/public/data/megareforma/actor-census.json"
ALIASES = {
    "juan-castro": "juan-luis-castro",
    "loreto-cravajal": "loreto-carvajal",
}


def _merge_aliases(actors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(actor["id"]): actor for actor in actors}
    for alias_id, canonical_id in ALIASES.items():
        alias = by_id.pop(alias_id, None)
        canonical = by_id.get(canonical_id)
        if alias is None or canonical is None:
            continue
        seen = {
            (mention["source_id"], mention["evidence_quote"].casefold())
            for mention in canonical["mentions"]
        }
        for mention in alias["mentions"]:
            key = (mention["source_id"], mention["evidence_quote"].casefold())
            if key not in seen:
                canonical["mentions"].append(mention)
                seen.add(key)
        canonical["mentions"].sort(
            key=lambda mention: (mention["source_id"], mention["evidence_quote"])
        )
        canonical["source_ids"] = sorted(set(canonical["source_ids"]) | set(alias["source_ids"]))
    return sorted(
        by_id.values(),
        key=lambda actor: (-len(actor["source_ids"]), actor["name"].casefold()),
    )


def main() -> int:
    payload = json.loads(ACTOR_CENSUS.read_text(encoding="utf-8"))
    actors = _merge_aliases(payload["actors"])
    enrich_actor_affiliations(actors)
    payload["actors"] = actors
    payload["coverage"]["actors_indexed"] = len(actors)
    payload["coverage"]["people"] = sum(actor["entity_kind"] == "person" for actor in actors)
    payload["coverage"]["institutions"] = sum(
        actor["entity_kind"] == "institution" for actor in actors
    )
    payload["coverage"]["detailed_profiles"] = sum(
        actor["profile_depth"] == "detailed" for actor in actors
    )
    payload["coverage"]["indexed_only"] = sum(
        actor["profile_depth"] == "indexed" for actor in actors
    )
    payload["coverage"]["accepted_mentions"] = sum(len(actor["mentions"]) for actor in actors)
    ACTOR_CENSUS.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
