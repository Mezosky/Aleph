from aleph.dossier.actor_census import (
    _action_is_self_attributed,
    _deterministic_actor_quote,
    _mention_is_grounded,
    merge_census,
    visible_article_text,
)
from aleph.dossier.deep import TOPICS
from scripts.analyze_megareforma_actors import _chunks, _profile_actor_type, _role_actor_type
from scripts.analyze_megareforma_deep import _apply_grounded_corrections


def test_deep_topic_contract_has_unique_complete_inventory() -> None:
    assert len(TOPICS) == 30
    assert len({topic.id for topic in TOPICS}) == len(TOPICS)
    assert all(topic.pages for topic in TOPICS)
    assert max(page for topic in TOPICS for page in topic.pages) == 46


def test_frozen_deep_audit_declares_the_original_blank_page() -> None:
    import json
    from pathlib import Path

    payload = json.loads(
        (
            Path(__file__).parents[1] / "frontend/public/data/megareforma/deep-analysis.json"
        ).read_text()
    )
    assert payload["coverage"]["blank_pages"] == [43]


def test_deep_review_overrides_model_conflicts_with_official_errata() -> None:
    topics = [
        {"id": "tobacco-smuggling", "fiscal_effect": "wrong"},
        {"id": "tax-stability", "risks_and_open_questions": ["unrelated RCA risk"]},
    ]
    assert _apply_grounded_corrections(topics) == 2
    assert "$103.730" in topics[0]["fiscal_effect"]
    assert all("RCA" not in risk for risk in topics[1]["risks_and_open_questions"])


def test_actor_text_extraction_excludes_scripts_and_prefers_article() -> None:
    content = b"""
    <html><body><nav>Navigation Person</nav><article>
    Mayor Example said the municipality would publish its figures.
    </article><script>Hidden Actor opposed everything.</script></body></html>
    """
    text = visible_article_text(content)
    assert "Mayor Example" in text
    assert "Navigation Person" not in text
    assert "Hidden Actor" not in text


def test_actor_audit_chunks_long_articles_without_losing_boundaries() -> None:
    text = "".join(str(index % 10) for index in range(31_000))
    chunks = _chunks(text, size=12_000, overlap=800)
    assert len(chunks) == 3
    assert chunks[0][-800:] == chunks[1][:800]
    assert chunks[1][-800:] == chunks[2][:800]
    assert chunks[-1].endswith(text[-1_000:])


def test_actor_mentions_require_named_self_action_about_the_reform() -> None:
    text = (
        "En el debate de la megareforma, Ana Pérez rechazó la rebaja del impuesto corporativo. "
        "En noticias relacionadas, el Gobierno impulsa un registro distinto."
    )
    actor = {"name": "Ana Pérez"}
    assert _mention_is_grounded(
        actor,
        {
            "action_or_position": "Ana Pérez rechazó la rebaja del impuesto corporativo.",
            "evidence_quote": "Ana Pérez rechazó la rebaja del impuesto corporativo",
        },
        text,
    )
    assert not _mention_is_grounded(
        {"name": "Gobierno"},
        {
            "action_or_position": "El Gobierno impulsa un registro distinto.",
            "evidence_quote": "el Gobierno impulsa un registro distinto",
        },
        "En noticias relacionadas, el Gobierno impulsa un registro distinto.",
    )
    assert not _mention_is_grounded(
        {"name": "Consejo Fiscal Autónomo"},
        {
            "action_or_position": "Será escuchado durante el debate del proyecto de ley.",
            "evidence_quote": "Consejo Fiscal Autónomo será escuchado durante el debate",
        },
        "El Consejo Fiscal Autónomo será escuchado durante el debate del proyecto de ley.",
    )


def test_actor_quote_is_extracted_by_code_not_copied_by_model() -> None:
    quote, reason = _deterministic_actor_quote(
        {"name": "Ana Pérez"},
        {
            "action_or_position": "Ana Pérez rechazó la rebaja del impuesto corporativo.",
            "source_id": "source",
        },
        "En la megareforma, Ana Pérez rechazó la rebaja del impuesto corporativo por su costo.",
    )
    assert reason is None
    assert quote is not None and "ana pérez rechazó" in quote

    quote, reason = _deterministic_actor_quote(
        {"name": "FMI"},
        {
            "action_or_position": "Las oposiciones han pedido que el FMI participe del debate.",
            "source_id": "source",
        },
        "En el proyecto de ley, las oposiciones han pedido que el FMI participe del debate.",
    )
    assert quote is None
    assert reason == "passive_mention_not_actor_action"


def test_institution_must_be_subject_of_its_attributed_action() -> None:
    institution = {"name": "Banco Central", "entity_kind": "institution"}
    assert _action_is_self_attributed(
        institution, "Banco Central publicó su evaluación de la reforma."
    )
    assert _action_is_self_attributed(institution, "Publicó su evaluación de la reforma.")
    assert not _action_is_self_attributed(
        institution, "Gael Yeomans pidió invitar al Banco Central al debate."
    )
    assert not _action_is_self_attributed(
        {"name": "Ministro de Hacienda", "entity_kind": "person"},
        "Fue criticado por no dialogar con los alcaldes.",
    )


def test_actor_census_merges_grounded_mentions_without_scoring_people() -> None:
    batch = {
        "rejected": 0,
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "actors": [
            {
                "name": "María Pérez",
                "entity_kind": "person",
                "actor_type": "mayor",
                "role": "Alcaldesa",
                "institution": "Municipalidad",
                "affiliation": "",
                "participation_summary": "Pidió datos fiscales verificables para su municipio.",
                "mentions": [
                    {
                        "source_id": "source-one",
                        "action_or_position": "Pidió publicar los datos fiscales municipales.",
                        "evidence_quote": "María Pérez pidió publicar los datos",
                    }
                ],
            }
        ],
    }
    result = merge_census([batch, batch], detailed_names={"maría pérez"})
    assert len(result["actors"]) == 1
    assert result["actors"][0]["profile_depth"] == "detailed"
    assert len(result["actors"][0]["mentions"]) == 1
    assert "score" not in result["actors"][0]


def test_actor_census_resolves_unique_surname_to_detailed_profile() -> None:
    batch = {
        "rejected": 0,
        "usage": {},
        "actors": [
            {
                "name": "alcalde Castro",
                "entity_kind": "person",
                "actor_type": "mayor",
                "role": "alcalde",
                "institution": "Renca",
                "affiliation": "",
                "mentions": [
                    {
                        "source_id": "source",
                        "action_or_position": "Cuestionó el impacto municipal de la reforma.",
                        "evidence_quote": "el alcalde Castro cuestionó el impacto municipal",
                    }
                ],
            }
        ],
    }
    result = merge_census([batch], detailed_names={"claudio castro": "Claudio Castro"})
    assert result["actors"][0]["name"] == "Claudio Castro"
    assert result["actors"][0]["profile_depth"] == "detailed"


def test_actor_census_normalizes_source_typo_and_named_municipal_collective() -> None:
    batch = {
        "rejected": 0,
        "usage": {},
        "actors": [
            {
                "name": "Loreto Cravajal",
                "entity_kind": "person",
                "actor_type": "legislator",
                "role": "senadora",
                "institution": "Senado",
                "affiliation": "",
                "mentions": [
                    {
                        "source_id": "senate",
                        "action_or_position": "Manifestó reparos sobre la menor recaudación.",
                        "evidence_quote": "Loreto Cravajal manifestó reparos",
                    }
                ],
            },
            {
                "name": "104 jefes comunales",
                "entity_kind": "person",
                "actor_type": "mayor",
                "role": "alcaldes firmantes",
                "institution": "",
                "affiliation": "",
                "mentions": [
                    {
                        "source_id": "letter",
                        "action_or_position": "Propusieron destinar la compensación al fondo común.",
                        "evidence_quote": "104 jefes comunales propusieron destinarla al fondo común",
                    }
                ],
            },
        ],
    }
    result = merge_census([batch], detailed_names={"loreto carvajal": "Loreto Carvajal"})
    by_name = {actor["name"]: actor for actor in result["actors"]}
    assert by_name["Loreto Carvajal"]["profile_depth"] == "detailed"
    assert by_name["104 jefes comunales"]["entity_kind"] == "institution"
    assert by_name["104 jefes comunales"]["actor_type"] == "municipal_association"


def test_detailed_profile_role_controls_actor_type() -> None:
    assert _profile_actor_type("Alcaldesa y vicepresidenta de la AChM") == "mayor"
    assert _profile_actor_type("Presidenta del Senado") == "legislator"
    assert _profile_actor_type("Ministro de Hacienda") == "government"
    assert _profile_actor_type("Líder del Partido de la Gente") == "other"
    assert _role_actor_type("Secretario general", "legislator") == "political_party"
