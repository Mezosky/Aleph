"""Offline synthesis of comparative evidence for the Megareforma dossier.

The model receives bounded, source-labelled evidence notes. It may explain how
that evidence bears on the Chilean proposal, but it cannot add references or
turn a conditional empirical result into a forecast for Chile.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TOPICS = {
    "corporate_tax_growth": {
        "title": "Impuestos corporativos, inversión y crecimiento",
        "question": "¿Bajar el impuesto a las empresas hace crecer la economía?",
        "source_ids": [
            "research-oecd-corporate-investment-2023",
            "research-aea-us-tax-cut-2024",
            "research-nber-tax-cuts-employment",
        ],
        "notes": (
            "OECD 2023: la inversión suele responder al costo de capital, pero la magnitud cambia "
            "por firma, activo y diseño. AEA 2024 sobre EE.UU. 2017: inversión tangible +11% en el "
            "consenso revisado; PIB de largo plazo menos de 1% y salarios menos de lo anunciado; "
            "recaudación corporativa cayó 40%. NBER: las rebajas estatales elevaron actividad sobre "
            "todo en recesiones. Ninguna estimación identifica el efecto de este proyecto chileno."
        ),
    },
    "fiscal_self_financing": {
        "title": "¿El crecimiento paga la rebaja?",
        "question": "¿Puede una rebaja tributaria autofinanciarse?",
        "source_ids": [
            "research-aea-us-tax-cut-2024",
            "research-nber-tax-cuts-employment",
            "cfa-comments",
            "dipres-financial-report",
        ],
        "notes": (
            "La revisión AEA encuentra crecimiento positivo pero una gran caída de recaudación, no "
            "autofinanciamiento. NBER encuentra efectos dependientes del ciclo. El informe DIPRES "
            "modela compensación con una trayectoria alternativa del PIB y supuestos explícitos; "
            "el CFA chileno reportó riesgos fiscales. Una proyección no es una observación causal."
        ),
    },
    "environmental_permits": {
        "title": "Permisos rápidos y protección ambiental",
        "question": "¿Acortar permisos mantiene la misma protección?",
        "source_ids": [
            "research-oecd-environmental-permitting",
            "dipres-financial-report",
            "supreme-court-report",
        ],
        "notes": (
            "OECD 2025: trámites largos y descoordinados pueden frenar inversión, incluso verde; "
            "simplificar funciona mejor con coordinación, capacidad técnica, digitalización y "
            "evaluación de riesgos. El informe chileno limita reevaluaciones y cautelares. Acortar "
            "plazos demuestra velocidad procedimental, no equivalencia de protección ambiental."
        ),
    },
    "housing_property_tax": {
        "title": "Vivienda, IVA y contribuciones",
        "question": "¿Las exenciones abaratan la vivienda y protegen a quien lo necesita?",
        "source_ids": [
            "research-oecd-housing-taxation",
            "dipres-financial-report",
            "ciper-final-compensation",
        ],
        "notes": (
            "OECD Housing Taxation: cuando la oferta responde poco, desgravaciones a propietarios "
            "pueden capitalizarse parcialmente en precios; los impuestos recurrentes a inmuebles "
            "son más eficientes que los de transacción, aunque hogares con patrimonio y poco ingreso "
            "pueden enfrentar iliquidez. El proyecto exige analizar focalización y compensación municipal."
        ),
    },
    "higher_education": {
        "title": "Gratuidad, acceso y costo fiscal",
        "question": "¿Postergar la expansión de gratuidad cambia la movilidad educativa?",
        "source_ids": [
            "research-oecd-chile-education-2025",
            "dipres-financial-report",
        ],
        "notes": (
            "OECD 2025 para Chile: la gratuidad coincide con una mejora de 7 puntos en acceso de "
            "jóvenes cuyos padres no terminaron secundaria entre 2012 y 2023, pero la asociación no "
            "aísla por sí sola causalidad; persisten barreras de preparación, calidad y financiamiento. "
            "El informe posterga umbrales futuros y estima ahorro, no el efecto educativo final."
        ),
    },
    "text_data_mining": {
        "title": "Minería de datos, innovación y derechos de autor",
        "question": "¿Una excepción amplia es necesaria para innovar?",
        "source_ids": [
            "research-wipo-text-data-mining",
            "dipres-financial-report",
        ],
        "notes": (
            "El estudio WIPO compara regímenes y muestra que acceso lícito, finalidad comercial o "
            "científica, seguridad de copias, opt-out y remuneración son decisiones separables. "
            "Permitir minería reduce costos de autorización, pero la evidencia comparada no demuestra "
            "que cualquier amplitud maximice innovación ni que sea neutral para titulares."
        ),
    },
}

THEORY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "minItems": 6,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"enum": list(TOPICS)},
                    "bottom_line": {"type": "string", "minLength": 40, "maxLength": 350},
                    "findings": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 4,
                        "items": {"type": "string", "minLength": 25, "maxLength": 260},
                    },
                    "application_to_reform": {
                        "type": "string",
                        "minLength": 40,
                        "maxLength": 500,
                    },
                    "limits": {"type": "string", "minLength": 30, "maxLength": 350},
                    "source_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "id",
                    "bottom_line",
                    "findings",
                    "application_to_reform",
                    "limits",
                    "source_ids",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["topics"],
    "additionalProperties": False,
}


def synthesize_theory_analysis(provider: Any) -> dict[str, Any]:
    evidence = "\n\n".join(
        f"TEMA {topic_id}\nFUENTES PERMITIDAS: {', '.join(spec['source_ids'])}\nNOTAS: {spec['notes']}"
        for topic_id, spec in TOPICS.items()
    )
    prompt = f"""Analiza estas seis preguntas usando EXCLUSIVAMENTE las notas etiquetadas.
Escribe en español claro para público general. Distingue asociación, efecto causal y proyección.
No decidas si una posición política es buena; identifica qué parte respalda la evidencia, qué parte
es condicional y qué datos chilenos faltan. No agregues fuentes y devuelve cada tema una sola vez.

{evidence}
"""
    response = provider.complete(
        prompt,
        schema=THEORY_SCHEMA,
        max_tokens=3600,
        timeout=900,
        purpose="megareforma_comparative_evidence",
    )
    parsed = getattr(response, "parsed", None)
    if not isinstance(parsed, Mapping):
        raise ValueError("comparative-evidence provider returned no parsed object")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in parsed["topics"]:
        topic_id = str(item["id"])
        if topic_id in seen or topic_id not in TOPICS:
            raise ValueError(f"duplicate or unknown comparative topic: {topic_id}")
        allowed = set(TOPICS[topic_id]["source_ids"])
        cited = set(item["source_ids"])
        if not cited or not cited <= allowed:
            raise ValueError(f"topic {topic_id} cited a source outside its evidence packet")
        seen.add(topic_id)
        output.append(
            {
                **item,
                "title": TOPICS[topic_id]["title"],
                "question": TOPICS[topic_id]["question"],
            }
        )
    if seen != set(TOPICS):
        raise ValueError("model did not return all comparative topics")
    return {
        "topics": output,
        "model": {
            "provider": response.provider,
            "name": response.model,
            "usage": response.usage.to_jsonable(),
            "structured_output_mode": response.structured_output_mode.value,
        },
    }
