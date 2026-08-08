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


def test_megareforma_legal_records_keep_procedural_safeguards() -> None:
    schema = json.loads((ROOT / "schemas" / "megareforma_dossier.json").read_text(encoding="utf-8"))
    dossier = json.loads(
        (ROOT / "frontend" / "public" / "data" / "megareforma" / "dossier.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(dossier)

    records = [
        (actor["id"], record) for actor in dossier["actors"] for record in actor["legal_record"]
    ]
    assert [actor_id for actor_id, _ in records] == ["ivan-moreira"]
    _, record = records[0]
    assert record["resolved"] is False
    assert len(record["presumption_note"]) >= 30
    assert record["source"]["url"].startswith("https://www.fiscaliadechile.cl/")
    assert "bias" not in record and "score" not in record

    record["presumption_note"] = None
    assert list(Draft202012Validator(schema).iter_errors(dossier))


def test_municipal_actor_index_is_complete_for_declared_corpus() -> None:
    data_root = ROOT / "frontend" / "public" / "data" / "megareforma"
    index = json.loads((data_root / "municipal-actors.json").read_text(encoding="utf-8"))
    sources = json.loads((data_root / "sources.json").read_text(encoding="utf-8"))
    known_sources = {item["id"] for item in [*sources["items"], *sources["gaps"]]}

    assert index["coverage"]["actors_indexed"] == len(index["actors"])
    assert len({actor["id"] for actor in index["actors"]}) == len(index["actors"])
    assert all(actor["public_record"] for actor in index["actors"])
    assert all(
        source_id in known_sources for actor in index["actors"] for source_id in actor["source_ids"]
    )
    assert "no pueden ser entrada" in index["coverage"]["blind_path_rule"]
