from aleph.dossier.actor_affiliations import (
    SENATE_ROSTER_URL,
    enrich_actor_affiliations,
)


def test_affiliations_distinguish_verified_independent_and_not_applicable() -> None:
    actors = [
        {
            "id": "pedro-araya",
            "entity_kind": "person",
            "affiliation": "",
        },
        {
            "id": "karim-bianchi",
            "entity_kind": "person",
            "affiliation": "",
        },
        {
            "id": "senado",
            "entity_kind": "institution",
            "affiliation": "Oposición",
        },
        {
            "id": "persona-sin-registro",
            "entity_kind": "person",
            "affiliation": "",
        },
    ]

    enrich_actor_affiliations(actors)

    assert actors[0]["affiliation"] == "Partido por la Democracia"
    assert actors[0]["affiliation_status"] == "verified_public_record"
    assert actors[0]["affiliation_source_url"] == SENATE_ROSTER_URL
    assert actors[1]["affiliation"] == "Independiente"
    assert actors[1]["affiliation_status"] == "independent_public_record"
    assert actors[2]["affiliation_status"] == "institutional_not_applicable"
    assert actors[2]["affiliation"] == ""
    assert actors[3]["affiliation_status"] == "not_documented"
