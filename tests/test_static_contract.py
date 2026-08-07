from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver

ROOT = Path(__file__).resolve().parents[1]


def test_actor_profiles_are_valid_and_attributed_only() -> None:
    schema_path = ROOT / "schemas" / "actor_profile.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "frontend" / "public" / "data" / "reforms" / "18216-05.json").read_text(
            encoding="utf-8"
        )
    )
    store = {}
    for path in (ROOT / "schemas").glob("*.json"):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        store[loaded["$id"]] = loaded
        store[path.name] = loaded
    resolver = RefResolver(base_uri=(ROOT / "schemas").as_uri() + "/", referrer=schema, store=store)
    Draft202012Validator(schema, resolver=resolver).validate(bundle["actor_profiles"])
    assert bundle["actor_profiles"]["usable_in_blind_evaluation"] is False
    assert all(not actor["legal_record"] for actor in bundle["actor_profiles"]["actors"])
