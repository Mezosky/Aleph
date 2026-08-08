from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_red_dot_records_are_personal_primary_source_records_only() -> None:
    census = _load("frontend/public/data/megareforma/actor-census.json")
    dossier = _load("frontend/public/data/megareforma/dossier.json")
    profiles = {actor["id"]: actor for actor in dossier["actors"]}

    personal_ids: set[str] = set()
    for actor in census["actors"]:
        records = profiles.get(actor["id"], {}).get("legal_record", actor.get("legal_record", []))
        if not records:
            continue
        personal_ids.add(actor["id"])
        assert actor["entity_kind"] == "person"
        for record in records:
            assert record["source"]["url"].startswith(
                (
                    "https://www.cde.cl/",
                    "https://www.fiscaliadechile.cl/",
                    "https://www.pjud.cl/",
                )
            )
            if not record["resolved"]:
                assert len(record["presumption_note"]) >= 30

    assert {
        "ivan-moreira",
        "karol-cariola",
        "miguel-angel-aguilera",
        "miguel-angel-calisto",
    } <= personal_ids
    assert "jorge-quiroz" not in personal_ids


def test_every_census_person_has_an_explicit_review_state_in_the_ui_contract() -> None:
    census = _load("frontend/public/data/megareforma/actor-census.json")
    dossier = _load("frontend/public/data/megareforma/dossier.json")
    audited_ids = {actor["id"] for actor in dossier["actors"]}
    audited_ids.update(
        actor["id"] for actor in census["actors"] if actor.get("official_record_audit")
    )

    people = [actor for actor in census["actors"] if actor["entity_kind"] == "person"]
    assert len(people) == census["coverage"]["people"]
    assert audited_ids <= {actor["id"] for actor in people}
    assert len(audited_ids) == 12
    assert len(people) - len(audited_ids) == 75
