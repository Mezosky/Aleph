"""Source-backed affiliation enrichment for the frozen Megarreforma actor census."""

from __future__ import annotations

from typing import Any

SENATE_ROSTER_URL = "https://www.senado.cl/senadoras-y-senadores/listado-de-senadoras-y-senadores"
AFFILIATION_VERIFIED_AT = "2026-08-08"

# The Senate roster explicitly labels both party membership and independence.
# Keep these values separate from parliamentary committee membership: a committee
# is useful context, but it is not evidence of party affiliation.
SENATE_AFFILIATIONS = {
    "alejandra-sepulveda": "Independiente",
    "alejandro-kusanovic": "Independiente",
    "arturo-squella": "Partido Republicano",
    "beatriz-sanchez": "Frente Amplio",
    "carlos-kuschel": "Renovación Nacional",
    "claudia-pascual": "Partido Comunista",
    "cristian-vial": "Independiente",
    "daniel-nunez": "Partido Comunista",
    "daniella-cicardini": "Partido Socialista",
    "danisa-astudillo": "Partido Socialista",
    "diego-ibanez": "Frente Amplio",
    "enrique-lee": "Independiente",
    "esteban-velasquez": "Federación Regionalista Verde Social",
    "fabiola-campillai": "Independiente",
    "fidel-espinoza": "Partido Socialista",
    "gaston-saavedra": "Partido Socialista",
    "ignacio-urrutia": "Partido Republicano",
    "ivan-flores": "Partido Demócrata Cristiano",
    "karim-bianchi": "Independiente",
    "karol-cariola": "Partido Comunista",
    "loreto-carvajal": "Partido por la Democracia",
    "luciano-cruz-coke": "Evolución Política",
    "matias-walker": "Demócratas",
    "miguel-angel-calisto": "Independiente",
    "pedro-araya": "Partido por la Democracia",
    "renzo-trisotti": "Partido Republicano",
    "ricardo-celis": "Partido por la Democracia",
    "rodolfo-carter": "Independiente",
    "rojo-edwards": "Independiente",
    "sergio-gahona": "Unión Demócrata Independiente",
    "vlado-mirosevic": "Partido Liberal",
    "ximena-ordenes": "Independiente",
    "yasna-provoste": "Partido Demócrata Cristiano",
}


def enrich_actor_affiliations(actors: list[dict[str, Any]]) -> None:
    """Annotate census actors without inferring affiliation from their opinions."""

    for actor in actors:
        if actor["entity_kind"] == "institution":
            # A party or coalition label belongs in the institution's identity/role,
            # not in a field intended to describe a person's affiliation.
            actor["affiliation"] = ""
            actor["affiliation_status"] = "institutional_not_applicable"
            continue

        actor_id = str(actor["id"])
        verified = SENATE_AFFILIATIONS.get(actor_id)
        if verified is not None:
            actor["affiliation"] = verified
            actor["affiliation_status"] = (
                "independent_public_record"
                if verified == "Independiente"
                else "verified_public_record"
            )
            actor["affiliation_source_url"] = SENATE_ROSTER_URL
            actor["affiliation_verified_at"] = AFFILIATION_VERIFIED_AT
        elif str(actor.get("affiliation", "")).strip():
            actor["affiliation_status"] = "reported_in_corpus"
        else:
            actor["affiliation_status"] = "not_documented"
