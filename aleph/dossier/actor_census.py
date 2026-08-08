"""Corpus-wide, quote-grounded actor census for frozen news snapshots."""

from __future__ import annotations

import html
import re
import unicodedata
from difflib import SequenceMatcher
from html.parser import HTMLParser
from typing import Any


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._focus = 0
        self.all_text: list[str] = []
        self.focus_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "svg", "noscript"}:
            self._skip += 1
        if tag in {"article", "main"}:
            self._focus += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self._skip:
            self._skip -= 1
        if tag in {"article", "main"} and self._focus:
            self._focus -= 1

    def handle_data(self, data: str) -> None:
        value = " ".join(html.unescape(data).split())
        if self._skip or not value:
            return
        self.all_text.append(value)
        if self._focus:
            self.focus_text.append(value)


def visible_article_text(content: bytes, *, max_chars: int = 10_000) -> str:
    parser = _VisibleText()
    parser.feed(content.decode("utf-8", errors="replace"))
    focus = " ".join(parser.focus_text)
    text = focus if len(focus) >= 40 else " ".join(parser.all_text)
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


def _normal(value: str) -> str:
    value = html.unescape(value).casefold().replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", value).strip()


def _key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return re.sub(
        r"[^a-z0-9]+",
        "-",
        "".join(c for c in decomposed if not unicodedata.combining(c)).casefold(),
    ).strip("-")


def _schema(source_ids: list[str]) -> dict[str, Any]:
    mention = {
        "type": "object",
        "properties": {
            "source_id": {"enum": source_ids},
            "action_or_position": {"type": "string", "minLength": 20, "maxLength": 300},
        },
        "required": ["source_id", "action_or_position"],
        "additionalProperties": False,
    }
    actor = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 2, "maxLength": 160},
            "entity_kind": {"enum": ["person", "institution"]},
            "actor_type": {
                "enum": [
                    "government",
                    "legislator",
                    "mayor",
                    "political_party",
                    "municipal_association",
                    "technical_body",
                    "judiciary",
                    "business",
                    "union",
                    "civil_society",
                    "academic",
                    "international_organization",
                    "other",
                ]
            },
            "role": {"type": "string", "maxLength": 220},
            "institution": {"type": "string", "maxLength": 220},
            "affiliation": {"type": "string", "maxLength": 160},
            "mentions": {"type": "array", "minItems": 1, "maxItems": 20, "items": mention},
        },
        "required": [
            "name",
            "entity_kind",
            "actor_type",
            "role",
            "institution",
            "affiliation",
            "mentions",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"actors": {"type": "array", "maxItems": 80, "items": actor}},
        "required": ["actors"],
        "additionalProperties": False,
    }


_PROMPT = """\
Construye un censo de actores sustantivos en estas fuentes sobre la Megarreforma chilena.

Incluye toda persona o institución que en el texto haga, defienda, cuestione, negocie, vote,
evalúe técnicamente o deba implementar una medida. Incluye alcaldes, parlamentarios, ministros,
partidos, asociaciones, órganos técnicos, tribunales, gremios, sindicatos y sociedad civil.

Excluye periodistas, autores de la nota, fotógrafos, personas en menús o noticias relacionadas,
usuarios de redes sociales, colectivos genéricos ("oposición", "oficialismo") y menciones
puramente protocolares. Ser invitado, citado, criticado o destinatario de una petición NO convierte
a alguien en actor: la fuente debe atribuirle su propia acción, posición, voto o evaluación.
No infieras afiliación ni cargo: si la fuente no los entrega usa cadena vacía. No evalúes si el
actor tiene razón. Usa en name la forma exacta visible en la fuente, incluso si es una sigla. Cada
mención debe usar el source_id exacto y describir sólo la acción atribuida; el pipeline localizará
y adjuntará la cita literal de forma determinística. Devuelve cada actor una sola vez por lote.

FUENTES:
{sources}
"""

_GENERIC_ACTORS = {"oposición", "oposiciones", "oficialismo", "parlamentarios", "alcaldes"}
_PASSIVE_ACTIONS = (
    "fue criticad",
    "fue cuestionad",
    "fue mencionad",
    "fueron criticad",
    "fueron cuestionad",
    "fueron mencionad",
    "ha sido solicitad",
    "será escuchad",
    "fue invitad",
    "ser invitad",
    "pidieron invitar",
    "solicitaron invitar",
    "destino de una acción",
    "han pedido que",
    "ha pedido que",
    "se haga partícipe",
    "se hagan partícipes",
)
_REFORM_MARKERS = (
    "megareforma",
    "reconstrucción nacional",
    "ley de reconstrucción",
    "proyecto de reconstrucción",
    "proyecto de ley",
    "contribuciones",
    "fondo común municipal",
    "impuesto corporativo",
    "primera categoría",
    "reforma tributaria",
    "gratuidad",
    "licencias médicas",
    "sence",
    "permiso ambiental",
    "invariabilidad tributaria",
    "ganancias de capital",
    "dfl2",
    "dfl 2",
    "herencias",
    "repatriación",
    "fondo de emergencia",
)
_STOPWORDS = {
    "ante",
    "como",
    "con",
    "del",
    "desde",
    "dijo",
    "el",
    "ella",
    "en",
    "fue",
    "la",
    "las",
    "los",
    "para",
    "por",
    "que",
    "se",
    "sin",
    "sobre",
    "una",
    "uno",
}
_ACTIVE_INSTITUTION_VERBS = (
    "acordó",
    "anunció",
    "aprobó",
    "cuestionó",
    "defendió",
    "estimó",
    "informó",
    "negoció",
    "presentó",
    "propuso",
    "propusieron",
    "publicó",
    "rechazó",
    "rechazaron",
    "se reunió",
    "señalaron",
    "solicitó",
    "sostuvo",
    "advirtió",
    "entregaron",
    "llamaron",
    "manifestaron",
    "valoraron",
)


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-záéíóúñ]{3,}", _normal(value)) if token not in _STOPWORDS
    }


def _action_is_self_attributed(item: dict[str, Any], action: str) -> bool:
    normalized = _normal(action)
    if any(pattern in normalized for pattern in _PASSIVE_ACTIONS):
        return False
    if item.get("entity_kind") != "institution":
        return True
    name = _normal(str(item.get("name", "")))
    named_start = (
        normalized.startswith(name)
        or normalized.startswith(f"el {name}")
        or normalized.startswith(f"la {name}")
    )
    return named_start or normalized.startswith(_ACTIVE_INSTITUTION_VERBS)


def _mention_rejection_reason(
    item: dict[str, Any], mention: dict[str, Any], text: str
) -> str | None:
    name = str(item.get("name", ""))
    quote = str(mention.get("evidence_quote", ""))
    action = str(mention.get("action_or_position", ""))
    normalized_text = _normal(text)
    normalized_quote = _normal(quote)
    position = normalized_text.find(normalized_quote)
    if position < 0 or len(normalized_quote) < 12:
        return "quote_not_literal_or_too_short"
    if _normal(name) in _GENERIC_ACTORS:
        return "generic_collective"
    name_tokens = _tokens(name)
    quote_tokens = _tokens(quote)
    if not name_tokens or not name_tokens.intersection(quote_tokens):
        return "actor_name_absent_from_quote"
    action_tokens = _tokens(action) - name_tokens
    if not action_tokens.intersection(quote_tokens - name_tokens):
        return "action_not_supported_by_quote"
    if any(pattern in _normal(action) for pattern in _PASSIVE_ACTIONS):
        return "passive_mention_not_actor_action"
    context = normalized_text[max(0, position - 1_000) : position + len(normalized_quote) + 1_000]
    if not any(marker in context for marker in _REFORM_MARKERS):
        return "context_not_about_reform"
    return None


def _mention_is_grounded(item: dict[str, Any], mention: dict[str, Any], text: str) -> bool:
    return _mention_rejection_reason(item, mention, text) is None


def _deterministic_actor_quote(
    item: dict[str, Any], mention: dict[str, Any], text: str
) -> tuple[str | None, str | None]:
    name = str(item.get("name", ""))
    action = str(mention.get("action_or_position", ""))
    normalized_name = _normal(name)
    normalized_text = _normal(text)
    if normalized_name in _GENERIC_ACTORS:
        return None, "generic_collective"
    if not _action_is_self_attributed(item, action):
        return None, "passive_mention_not_actor_action"
    name_tokens = _tokens(name)
    action_tokens = _tokens(action) - name_tokens
    if not normalized_name or not action_tokens:
        return None, "actor_name_or_action_too_weak"

    candidates: list[tuple[int, int]] = []
    cursor = 0
    while True:
        position = normalized_text.find(normalized_name, cursor)
        if position < 0:
            break
        broad = normalized_text[max(0, position - 1_000) : position + len(normalized_name) + 1_000]
        narrow = normalized_text[max(0, position - 180) : position + len(normalized_name) + 300]
        overlap = len(action_tokens.intersection(_tokens(narrow)))
        if overlap and any(marker in broad for marker in _REFORM_MARKERS):
            candidates.append((overlap, position))
        cursor = position + len(normalized_name)
    if not candidates:
        return None, "no_named_reform_context_supports_action"

    _, position = max(candidates)
    start = max(0, position - 90)
    end = min(len(normalized_text), position + len(normalized_name) + 240)
    if start:
        next_space = normalized_text.find(" ", start)
        start = next_space + 1 if next_space >= 0 else start
    if end < len(normalized_text):
        previous_space = normalized_text.rfind(" ", start, end)
        end = previous_space if previous_space > start else end
    return normalized_text[start:end], None


def census_batch(provider: Any, sources: list[tuple[str, str]]) -> dict[str, Any]:
    source_ids = [source_id for source_id, _ in sources]
    packet = "\n\n".join(f"[FUENTE {source_id}]\n{text}" for source_id, text in sources)
    response = provider.complete(
        _PROMPT.format(sources=packet),
        schema=_schema(source_ids),
        max_tokens=8000,
        timeout=900,
        purpose="megareforma_actor_census_batch",
    )
    payload = getattr(response, "parsed", None)
    items = payload.get("actors", []) if isinstance(payload, dict) else []
    text_by_source = dict(sources)
    accepted: list[dict[str, Any]] = []
    rejected = 0
    rejection_reasons: dict[str, int] = {}
    rejected_examples: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            rejected += 1
            continue
        mentions = []
        for mention in item.get("mentions", []):
            source_id = str(mention.get("source_id", ""))
            quote = None
            if source_id not in text_by_source:
                reason = "unknown_source_id"
            else:
                quote, reason = _deterministic_actor_quote(item, mention, text_by_source[source_id])
            if reason is not None:
                rejected += 1
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                if len(rejected_examples) < 20:
                    rejected_examples.append({"name": str(item.get("name", "")), "reason": reason})
                continue
            mentions.append({**dict(mention), "evidence_quote": quote})
        if mentions:
            accepted.append({**dict(item), "mentions": mentions})
        else:
            rejected += 1
    response_usage = getattr(getattr(response, "usage", None), "to_jsonable", lambda: {})()
    return {
        "actors": accepted,
        "rejected": rejected,
        "rejection_reasons": rejection_reasons,
        "rejected_examples": rejected_examples,
        "usage": response_usage,
    }


_PERSON_TITLES = re.compile(
    r"^(?:presidente|presidenta|ministro|ministra|senador|senadora|diputado|diputada|"
    r"alcalde|alcaldesa)\s+",
    re.IGNORECASE,
)
_INSTITUTION_ALIASES = {
    "cfa": "Consejo Fiscal Autónomo",
    "consejo fiscal autónomo (cfa)": "Consejo Fiscal Autónomo",
    "ejecutivo": "Gobierno",
    "gobierno de chile": "Gobierno",
    "poder ejecutivo": "Gobierno",
    "fa": "Frente Amplio",
    "frente amplio (fa)": "Frente Amplio",
    "pdg": "Partido de la Gente",
    "partido de la gente (pdg)": "Partido de la Gente",
    "ppd": "Partido por la Democracia",
    "rn": "Renovación Nacional",
    "udi": "Unión Demócrata Independiente",
}
_PERSON_ALIASES = {
    "josé garcía": "José García Ruminot",
    "juan castro": "Juan Luis Castro",
    "loreto cravajal": "Loreto Carvajal",
    "trisotti": "Renzo Trisotti",
}
_MUNICIPAL_COLLECTIVE = re.compile(
    r"^(?:\d+\s+(?:jefes|autoridades)\s+comunales|alcaldes(?:as)?\s+de\s+)",
    re.IGNORECASE,
)
_NON_ACTOR_PERSON = re.compile(
    r"^(?:adultos mayores|contribuyentes|beneficiarios|ciudadanos|empresas|municipalidades)\b",
    re.IGNORECASE,
)


def _canonical_person_name(name: str, detailed: dict[str, str]) -> str:
    stripped = _PERSON_TITLES.sub("", name).strip()
    normalized = _normal(stripped)
    if normalized in _PERSON_ALIASES:
        return _PERSON_ALIASES[normalized]
    if normalized in detailed:
        return detailed[normalized]
    matches = [
        display
        for known, display in detailed.items()
        if known.endswith(f" {normalized}") or known == normalized
    ]
    if len(matches) == 1:
        return matches[0]
    # Correct a single transcription error only when the full first name agrees
    # and exactly one detailed profile is a very close match. This resolves source
    # typos such as "Loreto Cravajal" without collapsing distinct surnames.
    words = normalized.split()
    fuzzy = [
        display
        for known, display in detailed.items()
        if len(words) >= 2
        and len(known.split()) == len(words)
        and known.split()[0] == words[0]
        and SequenceMatcher(None, known, normalized).ratio() >= 0.92
    ]
    return fuzzy[0] if len(fuzzy) == 1 else stripped


def merge_census(
    batches: list[dict[str, Any]], *, detailed_names: set[str] | dict[str, str]
) -> dict[str, Any]:
    detailed = (
        {_normal(name): name for name in detailed_names}
        if isinstance(detailed_names, set)
        else {_normal(name): display for name, display in detailed_names.items()}
    )
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    rejected = 0
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for batch in batches:
        rejected += int(batch["rejected"])
        for key in usage:
            usage[key] += int(batch["usage"].get(key, 0) or 0)
        for actor in batch["actors"]:
            actor = dict(actor)
            if actor["entity_kind"] == "person":
                actor["name"] = _canonical_person_name(str(actor["name"]), detailed)
                if _MUNICIPAL_COLLECTIVE.match(str(actor["name"])):
                    actor["entity_kind"] = "institution"
                    actor["actor_type"] = "municipal_association"
                elif _NON_ACTOR_PERSON.match(str(actor["name"])):
                    rejected += len(actor["mentions"]) + 1
                    continue
            else:
                actor["name"] = _INSTITUTION_ALIASES.get(
                    _normal(str(actor["name"])), str(actor["name"])
                )
            mentions_before = len(actor["mentions"])
            actor["mentions"] = [
                mention
                for mention in actor["mentions"]
                if _action_is_self_attributed(actor, str(mention["action_or_position"]))
            ]
            rejected += mentions_before - len(actor["mentions"])
            if not actor["mentions"]:
                rejected += 1
                continue
            identity = (str(actor["entity_kind"]), _normal(str(actor["name"])))
            current = merged.get(identity)
            if current is None:
                current = {**actor, "mentions": []}
                merged[identity] = current
            existing = {
                (mention["source_id"], _normal(mention["evidence_quote"]))
                for mention in current["mentions"]
            }
            for mention in actor["mentions"]:
                key = (mention["source_id"], _normal(mention["evidence_quote"]))
                if key not in existing:
                    current["mentions"].append(mention)
                    existing.add(key)
    actors = []
    for actor in merged.values():
        name = str(actor["name"])
        mentions = sorted(
            actor["mentions"], key=lambda item: (item["source_id"], item["evidence_quote"])
        )
        source_ids = sorted({mention["source_id"] for mention in mentions})
        actors.append(
            {
                "id": _key(name),
                **{key: value for key, value in actor.items() if key != "mentions"},
                "participation_summary": mentions[0]["action_or_position"],
                "profile_depth": "detailed" if _normal(name) in detailed else "indexed",
                "source_ids": source_ids,
                "mentions": mentions,
            }
        )
    actors.sort(key=lambda actor: (-len(actor["source_ids"]), _normal(actor["name"])))
    return {"actors": actors, "rejected": rejected, "usage": usage}
