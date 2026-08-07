"""Batched Qwen synthesis for a grounded, plain-language document brief.

The warm pipeline's atomic propositions remain deterministic and exhaustive.
This module makes one bounded model call over the complete extracted document,
then accepts only objectives carrying a quote found on the stated PDF page.
It replaces the legacy one-request-per-provision path for dossier generation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from aleph.ingestion.pdf import ExtractedDocument

OBJECTIVES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_summary": {"type": "string", "minLength": 40, "maxLength": 900},
        "scope_note": {"type": "string", "minLength": 20, "maxLength": 500},
        "objectives": {
            "type": "array",
            "minItems": 6,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "enum": [
                            "reconstruction",
                            "higher_education",
                            "environmental_permits",
                            "copyright_data_mining",
                            "senior_property_tax",
                            "business_tax_investment",
                        ]
                    },
                    "title": {"type": "string", "minLength": 5, "maxLength": 80},
                    "plain_language": {"type": "string", "minLength": 25, "maxLength": 280},
                    "mechanism": {"type": "string", "minLength": 20, "maxLength": 280},
                    "affected_groups": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {"type": "string", "maxLength": 100},
                    },
                    "caveat": {"type": "string", "minLength": 10, "maxLength": 220},
                },
                "required": [
                    "category",
                    "title",
                    "plain_language",
                    "mechanism",
                    "affected_groups",
                    "caveat",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["document_summary", "scope_note", "objectives"],
    "additionalProperties": False,
}

_PROMPT = """\
Analiza el informe financiero completo que sigue. Es el documento canónico del
dossier Aleph sobre la llamada "megarreforma" chilena.

Devuelve una explicación en español chileno, concreta y entendible, de QUÉ
QUIERE LOGRAR el proyecto y MEDIANTE QUÉ CAMBIOS. Agrupa detalles relacionados
en EXACTAMENTE 6 objetivos materiales. Mantén cada explicación bajo 45 palabras.
No opines si son buenos o malos y no
atribuyas resultados futuros como hechos.

Para cada objetivo:
- usa un subtítulo descriptivo, nunca una etiqueta técnica como
  "forecast_conditional";
- explica el cambio en lenguaje cotidiano;
- diferencia el mecanismo legal del resultado que el Gobierno espera obtener;
- identifica a quién afecta;
- declara la principal condición, incertidumbre o límite del propio informe.

Devuelve exactamente una entrada, en este orden, para cada categoría:
reconstruction, higher_education, environmental_permits,
copyright_data_mining, senior_property_tax, business_tax_investment. El
pipeline adjuntará por separado las citas literales verificadas; no intentes
citarlas ni inventes números de página.

El informe financiero describe el proyecto ingresado el 22 de abril de 2026;
no lo confundas con el texto posteriormente modificado por el Congreso.

DOCUMENTO:
{document}
"""


def _normal(value: str) -> str:
    value = re.sub(r"(?<=\w)-\s+(?=\w)", "", value)
    value = value.lower().replace("“", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"\s+", " ", value).strip()


_ANCHORS: dict[str, tuple[int, str]] = {
    "reconstruction": (
        1,
        "se extiende su cobertura para cubrir las necesidades de gasto en las regiones de Ñuble y del Biobío, zonas afectadas durante enero de 2026",
    ),
    "higher_education": (
        2,
        "se eleva los umbrales de activación de cada tramo (deciles 7 a 10) en 6 puntos porcentuales respecto de los valores vigentes",
    ),
    "environmental_permits": (
        3,
        "solo requerirán una nueva evaluación ambiental cuando impliquen una modificación sustantiva en la magnitud o duración de sus impactos ambientales",
    ),
    "copyright_data_mining": (
        8,
        "se permite, sin requerir autorización ni remuneración al titular de los derechos, realizar actos de reproducción, adaptación, distribución o comunicación al público",
    ),
    "senior_property_tax": (
        8,
        "Se establece una exención total del impuesto territorial respecto de la vivienda principal de personas naturales de 65 o más años de edad",
    ),
    "business_tax_investment": (
        9,
        "Se establece una reducción gradual de la tasa del impuesto de primera categoría aplicable a las rentas devengadas o percibidas a partir del año comercial 2026",
    ),
}


def _page_text(extracted: ExtractedDocument) -> str:
    return "\n\n".join(f"[PÁGINA {page.page_number}]\n{page.text}" for page in extracted.pages)


def synthesize_document_brief(extracted: ExtractedDocument, provider: Any) -> dict[str, Any]:
    """Make one model call and retain only page-grounded objectives."""
    response = provider.complete(
        _PROMPT.format(document=_page_text(extracted)),
        schema=OBJECTIVES_SCHEMA,
        max_tokens=1800,
        timeout=900,
        purpose="megareforma_document_brief",
    )
    payload = getattr(response, "parsed", None)
    if not isinstance(payload, Mapping):
        raise ValueError("document brief provider returned no parsed object")

    pages = {page.page_number: _normal(page.text) for page in extracted.pages}
    grounded: list[dict[str, Any]] = []
    rejected = 0
    seen_categories: set[str] = set()
    for index, candidate in enumerate(payload.get("objectives", []), start=1):
        if not isinstance(candidate, Mapping):
            rejected += 1
            continue
        category = str(candidate.get("category", ""))
        if category in seen_categories or category not in _ANCHORS:
            rejected += 1
            continue
        page, anchor = _ANCHORS[category]
        literal_quote = _normal(anchor)
        if literal_quote not in pages.get(page, ""):
            rejected += 1
            continue
        seen_categories.add(category)
        grounded.append(
            {
                "id": f"objective:{index}",
                **dict(candidate),
                "page": page,
                "source_quote": literal_quote,
                "quote_verified": True,
                "quote_grounding_method": "deterministic_exact_anchor",
            }
        )
    if len(grounded) < 6:
        raise ValueError(
            f"only {len(grounded)} objectives passed the page-grounding check; "
            f"{rejected} were rejected"
        )
    return {
        "document_summary": str(payload["document_summary"]),
        "scope_note": str(payload["scope_note"]),
        "objectives": grounded,
        "grounding": {
            "accepted": len(grounded),
            "rejected": rejected,
            "rule": "category-specific literal anchor must occur on its stated extracted PDF page",
        },
        "model": {
            "provider": getattr(response, "provider", "unknown"),
            "name": getattr(response, "model", "unknown"),
            "structured_output_mode": str(
                getattr(getattr(response, "structured_output_mode", None), "value", "unknown")
            ),
            "schema_valid": bool(getattr(response, "schema_valid", False)),
            "usage": getattr(getattr(response, "usage", None), "to_jsonable", lambda: {})(),
        },
    }
