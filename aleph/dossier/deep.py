"""Grounded, full-document topic audit for the Megareforma dossier."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from aleph.ingestion.pdf import ExtractedDocument


@dataclass(frozen=True, slots=True)
class TopicSpec:
    id: str
    title: str
    group: str
    pages: tuple[int, ...]


TOPICS: tuple[TopicSpec, ...] = (
    TopicSpec(
        "reconstruction-fund",
        "Fondo de reconstrucción por incendios",
        "gasto_y_reconstruccion",
        (1, 2, 18),
    ),
    TopicSpec(
        "higher-education-thresholds",
        "Umbrales para ampliar la gratuidad",
        "educacion",
        (2, 18, 19, 20),
    ),
    TopicSpec(
        "higher-education-moratorium",
        "Moratoria de nuevas instituciones en gratuidad",
        "educacion",
        (2, 19, 20),
    ),
    TopicSpec(
        "public-medical-leave",
        "Destitución por uso malicioso de licencias",
        "empleo_publico",
        (2, 3, 20, 21),
    ),
    TopicSpec("public-retirement", "Más cupos de incentivo al retiro", "empleo_publico", (3, 21)),
    TopicSpec(
        "environmental-permits",
        "Cambios a evaluación y litigación ambiental",
        "regulacion",
        (3, 4, 5),
    ),
    TopicSpec(
        "rca-restitution",
        "Restitución por anulación de permisos ambientales",
        "regulacion",
        (5, 6, 22, 23),
    ),
    TopicSpec(
        "aquaculture-relocalization", "Relocalización y monitoreo acuícola", "regulacion", (6, 7)
    ),
    TopicSpec(
        "procurement-sector-permits",
        "Compras públicas y autorizaciones sectoriales",
        "regulacion",
        (7,),
    ),
    TopicSpec(
        "cultural-heritage", "Hallazgos y permisos de patrimonio cultural", "regulacion", (7, 8)
    ),
    TopicSpec(
        "copyright-data-mining",
        "Minería de textos y datos con obras protegidas",
        "regulacion",
        (8,),
    ),
    TopicSpec("coin-transport", "Transporte y custodia de monedas", "regulacion", (8,)),
    TopicSpec(
        "senior-property-tax",
        "Exención de contribuciones para personas mayores",
        "tributos_permanentes",
        (8, 9, 22),
    ),
    TopicSpec(
        "tax-data-cross-check",
        "Cruce de datos para fiscalización tributaria",
        "tributos_permanentes",
        (9, 23),
    ),
    TopicSpec(
        "corporate-tax-rate",
        "Rebaja gradual del impuesto corporativo",
        "tributos_permanentes",
        (9, 10, 23, 24, 25, 26, 27),
    ),
    TopicSpec(
        "tax-integration",
        "Reintegración del sistema semiintegrado",
        "tributos_permanentes",
        (10, 11, 27, 28, 29),
    ),
    TopicSpec(
        "employment-tax-credit",
        "Crédito tributario por contratación",
        "tributos_permanentes",
        (11, 29, 30),
    ),
    TopicSpec(
        "capital-gains-tax",
        "Eliminación del 10% a ciertas ganancias de capital",
        "tributos_permanentes",
        (11, 12, 30),
    ),
    TopicSpec(
        "dfl2-benefits",
        "Ampliación de beneficios para viviendas DFL2",
        "tributos_permanentes",
        (12, 30, 31),
    ),
    TopicSpec(
        "tobacco-smuggling",
        "Sanciones contra el contrabando de tabaco",
        "tributos_permanentes",
        (12, 31),
    ),
    TopicSpec(
        "sence-credit",
        "Eliminación de la franquicia SENCE",
        "tributos_permanentes",
        (12, 13, 31, 32),
    ),
    TopicSpec(
        "aquaculture-unused-patents",
        "Patentes por no uso de concesiones acuícolas",
        "tributos_permanentes",
        (13, 32, 33),
    ),
    TopicSpec(
        "housing-vat",
        "Exención transitoria de IVA a viviendas nuevas",
        "tributos_transitorios",
        (13, 14, 33, 34),
    ),
    TopicSpec(
        "inheritance-advance",
        "Adelanto del impuesto a herencias y donaciones",
        "tributos_transitorios",
        (14, 15, 34, 35),
    ),
    TopicSpec(
        "foreign-assets",
        "Declaración y repatriación de capitales",
        "tributos_transitorios",
        (15, 16, 35, 36, 37),
    ),
    TopicSpec(
        "tax-stability",
        "Invariabilidad tributaria para grandes inversiones",
        "tributos_transitorios",
        (16, 17),
    ),
    TopicSpec(
        "substitute-taxes",
        "Impuestos sustitutivos sobre utilidades acumuladas",
        "tributos_transitorios",
        (17, 36, 37),
    ),
    TopicSpec(
        "treasury-debt-relief",
        "Rebaja de intereses y multas de deudas",
        "tributos_transitorios",
        (17, 18, 37),
    ),
    TopicSpec(
        "growth-effect",
        "Recaudación atribuida a mayor crecimiento",
        "efecto_fiscal",
        (23, 24, 38, 44, 45),
    ),
    TopicSpec(
        "consolidated-balance",
        "Balance fiscal consolidado y correcciones",
        "efecto_fiscal",
        (39, 40, 41, 42, 46),
    ),
)

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "reconstruction-fund": (
        "fondo de emergencia transitorio",
        "fondo de emergencia",
        "400.000 millones",
        "$400.000 millones",
        "$1.200.000 millones",
    ),
    "higher-education-thresholds": ("deciles", "umbral", "gratuidad"),
    "higher-education-moratorium": ("nuevas instituciones", "moratoria", "gratuidad"),
    "public-medical-leave": ("licencias médicas", "destitución"),
    "public-retirement": ("incentivo al retiro", "cupos de retiro"),
    "environmental-permits": ("evaluación ambiental", "permisos ambientales"),
    "rca-restitution": ("anulación de rca", "restitución", "resolución de calificación ambiental"),
    "aquaculture-relocalization": ("relocalización", "concesiones acuícolas"),
    "procurement-sector-permits": ("contratación pública", "autorizaciones sectoriales"),
    "cultural-heritage": ("monumentos nacionales", "patrimonio cultural"),
    "copyright-data-mining": ("minería de textos", "propiedad intelectual"),
    "coin-transport": ("monedas metálicas", "transporte de valores"),
    "senior-property-tax": ("contribuciones", "impuesto territorial"),
    "tax-data-cross-check": ("cruce de datos", "fiscalización tributaria"),
    "corporate-tax-rate": (
        "impuesto de primera categoría",
        "tasa corporativa",
        "impuesto corporativo",
        "rebaja de impuestos a las empresas",
    ),
    "tax-integration": ("reintegración", "sistema semi integrado", "sistema semiintegrado"),
    "employment-tax-credit": ("crédito tributario al empleo", "subsidio único al empleo"),
    "capital-gains-tax": ("ganancias de capital", "artículo 107"),
    "dfl2-benefits": ("dfl 2", "dfl2", "viviendas económicas"),
    "tobacco-smuggling": ("contrabando de tabaco", "contrabando"),
    "sence-credit": ("franquicia sence", "franquicia tributaria"),
    "aquaculture-unused-patents": ("patentes por no uso", "concesiones acuícolas"),
    "housing-vat": ("iva a la vivienda", "iva a viviendas", "viviendas nuevas"),
    "inheritance-advance": ("herencia y donaciones", "adelanto de impuesto"),
    "foreign-assets": ("bienes en el extranjero", "repatriación de capitales"),
    "tax-stability": ("invariabilidad tributaria", "estabilidad tributaria"),
    "substitute-taxes": ("impuestos sustitutivos", "utilidades acumuladas"),
    "treasury-debt-relief": ("intereses y multas", "tesorería general"),
    "growth-effect": ("mayor crecimiento", "elasticidad ingresos", "efecto crecimiento"),
    "consolidated-balance": ("efecto fiscal neto", "balance fiscal", "consolidado"),
}


def _normal(value: str) -> str:
    value = re.sub(r"(?<=\w)-\s+(?=\w)", "", value)
    value = value.casefold().replace("“", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"\s+", " ", value).strip()


def _schema(ids: list[str]) -> dict[str, Any]:
    item = {
        "type": "object",
        "properties": {
            "topic_id": {"enum": ids},
            "what_changes": {"type": "string", "minLength": 30, "maxLength": 360},
            "mechanism": {"type": "string", "minLength": 30, "maxLength": 360},
            "government_goal": {"type": "string", "minLength": 20, "maxLength": 260},
            "affected_groups": {
                "type": "array",
                "minItems": 1,
                "maxItems": 7,
                "items": {"type": "string", "maxLength": 90},
            },
            "fiscal_effect": {"type": "string", "minLength": 20, "maxLength": 360},
            "assumptions": {
                "type": "array",
                "maxItems": 5,
                "items": {"type": "string", "maxLength": 170},
            },
            "risks_and_open_questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {"type": "string", "maxLength": 180},
            },
        },
        "required": [
            "topic_id",
            "what_changes",
            "mechanism",
            "government_goal",
            "affected_groups",
            "fiscal_effect",
            "assumptions",
            "risks_and_open_questions",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "topics": {"type": "array", "minItems": len(ids), "maxItems": len(ids), "items": item}
        },
        "required": ["topics"],
        "additionalProperties": False,
    }


_PROMPT = """\
Eres el analista documental de Aleph. Lee TODAS las páginas entregadas del informe financiero
chileno IF 84/2026. Produce una ficha profunda para cada tema solicitado y exactamente una por id.

Reglas:
- Explica lo que cambia jurídicamente; no lo confundas con el resultado que el Gobierno espera.
- El efecto fiscal debe decir qué cuantifica el informe y qué no, incluyendo horizonte o supuestos
  cuando estén en las páginas. Si no hay cuantificación separada, dilo expresamente.
- No completes información desde memoria ni desde noticias.
- Identifica costos, beneficiarios, condiciones, riesgos de implementación y preguntas abiertas.
- El pipeline adjunta una cita literal verificada por separado; no inventes citas ni páginas.
- No emitas un juicio ideológico ni trates una proyección como un hecho observado.
- Sé compacto: máximo 45 palabras por campo narrativo y 25 por elemento de lista.

TEMAS:
{topics}

PÁGINAS DEL INFORME:
{pages}
"""


def synthesize_deep_topics(
    extracted: ExtractedDocument, provider: Any, *, batch_size: int = 5
) -> dict[str, Any]:
    """Analyse all declared topics and reject any item without a page-grounded quote."""
    page_map = {page.page_number: page.text for page in extracted.pages}
    output: list[dict[str, Any]] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for start in range(0, len(TOPICS), batch_size):
        batch = TOPICS[start : start + batch_size]
        page_numbers = sorted({page for spec in batch for page in spec.pages})
        packet = "\n\n".join(f"[PÁGINA {page}]\n{page_map[page]}" for page in page_numbers)
        topic_list = "\n".join(
            f"- {spec.id}: {spec.title} (páginas permitidas: {', '.join(map(str, spec.pages))})"
            for spec in batch
        )
        response = provider.complete(
            _PROMPT.format(topics=topic_list, pages=packet),
            schema=_schema([spec.id for spec in batch]),
            max_tokens=2100,
            timeout=900,
            purpose="megareforma_deep_topic_batch",
        )
        payload = getattr(response, "parsed", None)
        response_usage = getattr(getattr(response, "usage", None), "to_jsonable", lambda: {})()
        for key in usage:
            usage[key] += int(response_usage.get(key, 0) or 0)
        items = payload.get("topics", []) if isinstance(payload, dict) else []
        by_id = {str(item.get("topic_id")): item for item in items if isinstance(item, dict)}
        expected = {spec.id for spec in batch}
        if set(by_id) != expected:
            raise ValueError(
                f"deep topic batch mismatch: expected {sorted(expected)}, got {sorted(by_id)}"
            )
        for spec in batch:
            item = dict(by_id[spec.id])
            page, quote = _deterministic_anchor(spec, page_map)
            output.append(
                {
                    "id": spec.id,
                    "title": spec.title,
                    "group": spec.group,
                    "pages": list(spec.pages),
                    **{key: value for key, value in item.items() if key != "topic_id"},
                    "source_quote": quote,
                    "source_page": page,
                    "quote_verified": True,
                }
            )
    return {
        "document_pages": extracted.page_count,
        "topics_declared": len(TOPICS),
        "topics": output,
        "batches": (len(TOPICS) + batch_size - 1) // batch_size,
        "usage": usage,
    }


def _deterministic_anchor(spec: TopicSpec, page_map: dict[int, str]) -> tuple[int, str]:
    """Attach a normalized continuous excerpt containing a declared topic keyword."""
    for page in spec.pages:
        normalized = _normal(page_map[page])
        for keyword in TOPIC_KEYWORDS[spec.id]:
            folded = _normal(keyword)
            position = normalized.find(folded)
            if position < 0:
                continue
            start = max(0, position - 55)
            end = min(len(normalized), position + len(folded) + 170)
            if start:
                next_space = normalized.find(" ", start)
                start = next_space + 1 if next_space >= 0 else start
            if end < len(normalized):
                previous_space = normalized.rfind(" ", start, end)
                end = previous_space if previous_space > start else end
            return page, normalized[start:end]
    raise ValueError(f"{spec.id}: no deterministic anchor found on declared pages")
