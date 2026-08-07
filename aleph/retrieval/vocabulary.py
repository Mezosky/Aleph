"""Warm phase 4 — the words Aleph will go looking with, and why they are not the title.

Searching for a document's official title finds almost nothing. Instruments are
debated under nicknames the drafters never used, cited by file numbers that
appear nowhere in the text, covered in trade press that names the sector but
never the bill, and referred to across languages the source was not written in.
A pipeline that queries the PDF title therefore under-collects systematically —
and then, fatally, reports the resulting silence as an absence of coverage. The
evidence base looks thin, readiness looks honest, and the whole thing is an
artefact of a bad query.

This module exists to make that failure visible and then to fix it. Terms are
mined into ten fixed sets, so an empty set is a *reportable gap* rather than an
invisible one; every term records how it was derived, so a vocabulary built
mostly from guesses can be recognised as weaker than one lifted from the text;
and queries are generated per **source type**, because the phrasing that finds a
statute in a legislative register is not the phrasing that finds commentary in a
news archive, and one generic query silently over-collects journalism and
under-collects primary documents. That imbalance would then propagate into every
downstream diversity and independence measure as if it were a fact about the
world.

Two constraints are worth stating explicitly.

**Nothing here is topical.** There is no list of policy areas, no jurisdiction,
no institution and no subject vocabulary. Everything is mined from the document
in front of it — its identifiers, its headings, its definitions, its repeated
phrases, its own ``Long Name (LN)`` introductions — plus whatever the topic graph
resolved. A document in a language Aleph has never seen still produces
identifiers, phrases and provision names.

**Weights are search-utility only.** A term's weight says how likely it is to
retrieve relevant material without flooding the results. It carries no
evaluative meaning about the subject, and ``political_terminology`` in particular
is collected so that Aleph can *find* every side of a debate, including framings
it does not adopt. Presence there is a description of public usage and must never
weight or filter a factual verdict.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from aleph.core.enums import (
    DataStatus,
    EvidenceTier,
    QuerySyntax,
    SourceKind,
    TargetSourceType,
    TermSource,
)
from aleph.core.models import (
    SCHEMA_VERSION,
    DocumentModel,
    GeneratedQuery,
    SearchVocabulary,
    SourceRegistryEntry,
    Span,
    TermSets,
    TopicGraph,
    VocabularyTerm,
)
from aleph.propositions.extract import (
    GENERIC_PROFILE,
    CompletionProvider,
    LinguisticProfile,
    profile_for_text,
)
from aleph.propositions.graph import ACRONYM_INTRO_RE, acronym_matches

__all__ = [
    "VOCABULARY_VERSION",
    "QueryAudience",
    "AUDIENCE_PLAN",
    "AudiencePlan",
    "TERM_SET_NAMES",
    "SET_AUDIENCES",
    "mine_abbreviations",
    "identifier_variants",
    "mine_phrases",
    "normalise_term",
    "term_weight",
    "generate_queries",
    "LLM_VOCABULARY_SCHEMA",
    "build_search_vocabulary",
]

VOCABULARY_VERSION: Final[str] = "1.0.0"

_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
_NON_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[^\w\s./-]+", re.UNICODE)
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[^\W_]+", re.UNICODE)
_HAS_DIGIT_RE: Final[re.Pattern[str]] = re.compile(r"\d")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _clean_term(text: str) -> str:
    """Tidy a mined string into a usable query term.

    Brackets are balanced rather than stripped: a term cut mid-parenthesis
    (``"...de Agua (GCIA"``) matches nothing and would sit in the vocabulary
    looking like coverage. Where an opener has no closer, the term is truncated
    at the opener; a stray closer is simply dropped.
    """
    cleaned = _WS_RE.sub(" ", text).strip().strip("«»\"'“”,;:·•")
    opens, closes = cleaned.count("("), cleaned.count(")")
    if opens > closes:
        cleaned = cleaned[: cleaned.rfind("(")]
    elif closes > opens:
        cleaned = cleaned.replace(")", "")
    return _WS_RE.sub(" ", cleaned).strip().strip("«»\"'“”,;:-–—·•")


def normalise_term(text: str) -> str:
    """Casefolded, accent-stripped, punctuation-flattened form used for dedup.

    Two spellings of one term must not become two terms: a duplicate inflates the
    apparent breadth of a vocabulary and, through it, the apparent completeness of
    retrieval.
    """
    folded = _fold(text)
    return _WS_RE.sub(" ", _NON_WORD_RE.sub(" ", folded)).strip()


# ---------------------------------------------------------------------------
# Query planning
#
# Named audiences rather than raw enum values, because the interesting design
# decision is *who a query is for*. Each audience fixes the source type it is
# routed to, the tier of artefact it is expected to return, and how early it
# should run. Nothing here is aimed at a position, only at a kind of source.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AudiencePlan:
    """How one audience turns a term into a concrete query."""

    target_source_type: TargetSourceType
    expected_tier: EvidenceTier
    source_kinds: tuple[SourceKind, ...]
    base_priority: int
    rationale: str


class QueryAudience:
    """The kinds of source a vocabulary term is aimed at.

    A plain namespace of string constants rather than an enum: these are not part
    of the published data contract — the contract records the resulting
    ``target_source_type`` — and keeping them out of :mod:`aleph.core.enums`
    avoids implying that consumers should branch on them.
    """

    PRIMARY: Final[str] = "primary"
    LEGISLATIVE: Final[str] = "legislative"
    TECHNICAL: Final[str] = "technical"
    STATISTICAL: Final[str] = "statistical"
    ACADEMIC: Final[str] = "academic"
    NEWS: Final[str] = "news"
    STATEMENT: Final[str] = "statement"
    OPEN_WEB: Final[str] = "open_web"


AUDIENCE_PLAN: Final[dict[str, AudiencePlan]] = {
    QueryAudience.PRIMARY: AudiencePlan(
        target_source_type=TargetSourceType.GOVERNMENT_BODY,
        expected_tier=EvidenceTier.PRIMARY_DOCUMENT,
        source_kinds=(SourceKind.GOVERNMENT_BODY,),
        base_priority=1,
        rationale="Reaches the issuing body's own publication, which establishes what the text says.",
    ),
    QueryAudience.LEGISLATIVE: AudiencePlan(
        target_source_type=TargetSourceType.LEGISLATURE,
        expected_tier=EvidenceTier.LEGISLATIVE_RECORD,
        source_kinds=(SourceKind.LEGISLATURE,),
        base_priority=1,
        rationale="Reaches the procedural record: versions, amendments, committee stages.",
    ),
    QueryAudience.TECHNICAL: AudiencePlan(
        target_source_type=TargetSourceType.GOVERNMENT_BODY,
        expected_tier=EvidenceTier.OFFICIAL_TECHNICAL_REPORT,
        source_kinds=(SourceKind.GOVERNMENT_BODY, SourceKind.NGO),
        base_priority=2,
        rationale="Reaches impact assessments and technical annexes that quantify the instrument.",
    ),
    QueryAudience.STATISTICAL: AudiencePlan(
        target_source_type=TargetSourceType.STATISTICS_AGENCY,
        expected_tier=EvidenceTier.STATISTICAL_DATASET,
        source_kinds=(SourceKind.STATISTICS_AGENCY,),
        base_priority=2,
        rationale="Reaches the baseline data a quantitative claim can be checked against.",
    ),
    QueryAudience.ACADEMIC: AudiencePlan(
        target_source_type=TargetSourceType.ACADEMIC,
        expected_tier=EvidenceTier.PEER_REVIEWED,
        source_kinds=(SourceKind.ACADEMIC,),
        base_priority=3,
        rationale="Reaches methodological critique that popular phrasing never surfaces.",
    ),
    QueryAudience.NEWS: AudiencePlan(
        target_source_type=TargetSourceType.NEWS_OUTLET,
        expected_tier=EvidenceTier.JOURNALISM,
        source_kinds=(SourceKind.NEWS_OUTLET,),
        base_priority=3,
        rationale="Reaches contemporaneous reporting, which is where public claims enter the record.",
    ),
    QueryAudience.STATEMENT: AudiencePlan(
        target_source_type=TargetSourceType.NEWS_OUTLET,
        expected_tier=EvidenceTier.POLITICAL_STATEMENT,
        source_kinds=(SourceKind.NEWS_OUTLET, SourceKind.NGO),
        base_priority=4,
        rationale=(
            "Reaches what actors said about the instrument. Strong evidence that a claim "
            "was made, weak evidence that it is true; tiering keeps the two apart."
        ),
    ),
    QueryAudience.OPEN_WEB: AudiencePlan(
        target_source_type=TargetSourceType.SEARCH_ENGINE,
        expected_tier=EvidenceTier.JOURNALISM,
        source_kinds=(),
        base_priority=5,
        rationale="Fallback for coverage outside the registry, including unanticipated sources.",
    ),
}

TERM_SET_NAMES: Final[tuple[str, ...]] = (
    "official_names",
    "common_names",
    "identifiers",
    "abbreviations",
    "political_terminology",
    "technical_terminology",
    "sector_terminology",
    "synonyms",
    "provision_names",
    "actor_terms",
)

SET_AUDIENCES: Final[dict[str, tuple[str, ...]]] = {
    "identifiers": (
        QueryAudience.PRIMARY,
        QueryAudience.LEGISLATIVE,
        QueryAudience.NEWS,
        QueryAudience.TECHNICAL,
    ),
    "official_names": (
        QueryAudience.PRIMARY,
        QueryAudience.LEGISLATIVE,
        QueryAudience.ACADEMIC,
        QueryAudience.NEWS,
    ),
    "common_names": (QueryAudience.NEWS, QueryAudience.STATEMENT, QueryAudience.OPEN_WEB),
    "abbreviations": (QueryAudience.TECHNICAL, QueryAudience.ACADEMIC, QueryAudience.NEWS),
    "technical_terminology": (
        QueryAudience.ACADEMIC,
        QueryAudience.TECHNICAL,
        QueryAudience.STATISTICAL,
    ),
    "sector_terminology": (
        QueryAudience.STATISTICAL,
        QueryAudience.TECHNICAL,
        QueryAudience.NEWS,
    ),
    "actor_terms": (QueryAudience.PRIMARY, QueryAudience.NEWS, QueryAudience.STATEMENT),
    "provision_names": (
        QueryAudience.LEGISLATIVE,
        QueryAudience.TECHNICAL,
        QueryAudience.NEWS,
    ),
    "synonyms": (QueryAudience.NEWS, QueryAudience.OPEN_WEB),
    "political_terminology": (QueryAudience.NEWS, QueryAudience.STATEMENT),
}
"""Which audiences each term set is worth spending a query on.

An identifier is the term that finds the primary record and is wasted on an
academic index; a nickname is the term that finds the argument and is useless in
a statute register. Spending every term on every audience would not be thorough,
it would be noise that later looks like breadth.
"""

#: Base retrieval value by derivation. A phrase lifted from the document is
#: evidence about the document; a model-expanded synonym is a guess, and the gap
#: between the two must survive into the weights or a vocabulary of guesses will
#: look as strong as a vocabulary of facts.
_SOURCE_BASE_WEIGHT: Final[dict[TermSource, float]] = {
    TermSource.IDENTIFIER: 0.95,
    TermSource.TITLE: 0.85,
    TermSource.HEADING: 0.7,
    TermSource.ENTITY: 0.68,
    TermSource.PROVISION_HEADING: 0.62,
    TermSource.DEFINITION: 0.58,
    TermSource.MANUAL: 0.7,
    TermSource.REGISTRY: 0.55,
    TermSource.ABBREVIATION_EXPANSION: 0.52,
    TermSource.SYNONYM_EXPANSION: 0.42,
    TermSource.TRANSLATION: 0.4,
    TermSource.MODEL_EXPANSION: 0.35,
}

#: Which set wins when the same normalised term is mined twice. Ordered by how
#: much the set tells a retrieval planner: an identifier that also appears as a
#: heading is an identifier.
_SET_PRECEDENCE: Final[tuple[str, ...]] = (
    "identifiers",
    "official_names",
    "common_names",
    "abbreviations",
    "provision_names",
    "actor_terms",
    "technical_terminology",
    "sector_terminology",
    "political_terminology",
    "synonyms",
)


# ---------------------------------------------------------------------------
# Mining
# ---------------------------------------------------------------------------


def mine_abbreviations(document: DocumentModel) -> list[tuple[str, str]]:
    """Find the short forms a document introduces for itself.

    Only ``Long Name (LN)`` introductions whose letters match the initials of the
    expansion are kept. Without that check every parenthetical in the text would
    be registered as an acronym, and the vocabulary would fill with cross-
    references and units — terms that retrieve nothing and make the set look
    richer than it is.

    Returns:
        ``(acronym, expansion)`` pairs, deduplicated and sorted.
    """
    corpus = _document_corpus(document)
    found: dict[str, str] = {}
    for chunk in corpus:
        for match in ACRONYM_INTRO_RE.finditer(chunk):
            expansion, acronym = match.group(1).strip(), match.group(2).strip()
            if not acronym_matches(acronym, expansion):
                continue
            key = acronym.upper()
            if key not in found or expansion < found[key]:
                found[key] = _WS_RE.sub(" ", expansion)
    return sorted(found.items())


def identifier_variants(value: str) -> list[str]:
    """Mechanical spellings of one formal identifier.

    A file or bulletin number is the single highest-precision retrieval term
    there is — it finds the record rather than commentary about it — and it is
    also the term most often written three different ways: with and without
    grouping separators, with and without a suffix, spaced or hyphenated. Missing
    one spelling loses the primary record entirely, so all of them are generated
    mechanically. Nothing here parses meaning; it only permutes punctuation.
    """
    raw = value.strip()
    if not raw:
        return []
    variants = {raw}
    no_dots = raw.replace(".", "")
    variants.add(no_dots)
    variants.add(raw.replace(".", " "))
    variants.add(no_dots.replace("-", " "))
    variants.add(no_dots.replace("/", " "))
    variants.add(raw.replace("-", "/"))
    variants.add(raw.replace("/", "-"))
    head = re.split(r"[-/]", raw, maxsplit=1)[0]
    if head and head != raw and len(re.sub(r"\D", "", head)) >= 4:
        # The stem alone ("18.216" from "18.216-05") is how a number is quoted in
        # running prose more often than the full form.
        variants.add(head)
        variants.add(head.replace(".", ""))
    return sorted(v for v in (_WS_RE.sub(" ", v).strip() for v in variants) if len(v) >= 3)


def mine_phrases(
    texts: Sequence[str],
    profile: LinguisticProfile,
    *,
    min_count: int = 2,
    max_terms: int = 30,
    sizes: Sequence[int] = (2, 3, 4),
) -> list[tuple[str, int]]:
    """Mine repeated multi-word phrases, using function words only as a filter.

    Repetition is the signal: a phrase a document uses several times is a phrase
    the debate about it will use too. Function words are stripped from the edges
    of a candidate rather than from the middle, so "consumo industrial de agua"
    survives while "de agua y" does not.

    Works with :data:`~aleph.propositions.extract.GENERIC_PROFILE`, whose stopword
    set is empty — the length and repetition filters alone still produce usable
    phrases, which is what keeps this function viable for a document in a
    language Aleph has no profile for.

    Returns:
        ``(phrase, count)`` pairs, most frequent first, ties broken
        lexicographically so the result is reproducible.
    """
    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    for text in texts:
        for sentence in re.split(r"[.;:!?\n]", text):
            tokens = _TOKEN_RE.findall(sentence)
            if len(tokens) < min(sizes):
                continue
            for size in sizes:
                for index in range(len(tokens) - size + 1):
                    window = tokens[index : index + size]
                    if any(len(t) < 3 or _HAS_DIGIT_RE.search(t) for t in window):
                        continue
                    folded = [_fold(t) for t in window]
                    if folded[0] in profile.stopwords or folded[-1] in profile.stopwords:
                        continue
                    if all(t in profile.stopwords for t in folded):
                        continue
                    phrase = " ".join(window)
                    key = " ".join(folded)
                    counts[key] += 1
                    display.setdefault(key, phrase)
    ranked = sorted(
        ((key, count) for key, count in counts.items() if count >= min_count),
        key=lambda item: (-item[1], item[0]),
    )
    return [(display[key], count) for key, count in ranked[:max_terms]]


def _document_corpus(document: DocumentModel) -> list[str]:
    """Every stretch of the document's own words the miners may read."""
    chunks: list[str] = [document.identity.title]
    if document.identity.subtitle:
        chunks.append(document.identity.subtitle)
    if document.identity.short_title:
        chunks.append(document.identity.short_title)
    if document.identity.summary:
        chunks.append(document.identity.summary)
    stack = list(document.structure.sections)
    while stack:
        section = stack.pop()
        chunks.append(section.heading)
        stack.extend(section.children)
    for provision in document.provisions:
        if provision.title:
            chunks.append(provision.title)
        chunks.append(provision.text)
    for definition in document.definitions:
        chunks.append(f"{definition.term}. {definition.definition_text}")
    return [chunk for chunk in chunks if chunk and chunk.strip()]


# ---------------------------------------------------------------------------
# Weighting
# ---------------------------------------------------------------------------


def term_weight(
    text: str,
    source: TermSource,
    *,
    occurrences: int = 1,
    ambiguous: bool = False,
) -> float:
    """Expected retrieval value of a term, in [0,1].

    The formula is deliberately simple and stated in full so a thin vocabulary
    can be diagnosed rather than guessed at:

    * a base by derivation — text lifted from the document outranks a generated
      guess, because the two are different kinds of thing;
    * a specificity adjustment — a two-to-five word phrase is the sweet spot; a
      single short token collides with ordinary usage and floods results, and a
      very long phrase matches nothing;
    * a small, capped repetition bonus — a term the document uses repeatedly is
      more likely to be the term the debate uses, but repetition inside one
      document is weak evidence and must not dominate;
    * a penalty for a term flagged ambiguous.

    This is a search-utility number. It says nothing about the subject and must
    never be read as importance, credibility or salience in the world.
    """
    base = _SOURCE_BASE_WEIGHT.get(source, 0.4)
    tokens = _TOKEN_RE.findall(text)
    count = len(tokens)
    if count == 0:
        return 0.0
    if count == 1:
        longest = len(tokens[0])
        specificity = -0.25 if longest <= 3 else (-0.1 if longest <= 5 else 0.0)
    elif count <= 5:
        specificity = 0.08
    elif count <= 8:
        specificity = -0.05
    else:
        specificity = -0.2
    repetition = min(0.08, 0.02 * max(0, occurrences - 1))
    penalty = -0.15 if ambiguous else 0.0
    return round(max(0.0, min(1.0, base + specificity + repetition + penalty)), 3)


# ---------------------------------------------------------------------------
# Query generation
# ---------------------------------------------------------------------------


def generate_queries(
    term: VocabularyTerm,
    *,
    audiences: Sequence[str],
    registry: Sequence[SourceRegistryEntry] = (),
    date_from: str | None = None,
    date_to: str | None = None,
    context_terms: Sequence[str] = (),
    term_id: str | None = None,
) -> list[GeneratedQuery]:
    """Turn one term into concrete queries, one per audience.

    Routing is by :class:`~aleph.core.enums.SourceKind`, so a query aimed at a
    statistics agency is only ever sent to registered statistics agencies. That
    is the whole point of typing queries: the same subject needs different
    phrasing in a statute register, a data portal and a news archive, and a
    single generic query would return a pile of commentary that later reads as
    thorough coverage.

    Where the term is multi-word it is quoted, and where registry entries match
    the query is marked ``site_scoped`` — an unquoted multi-word term returns
    noise, and noise is the failure mode that is hardest to see afterwards.
    """
    out: list[GeneratedQuery] = []
    enabled = [entry for entry in registry if entry.enabled]
    for audience in audiences:
        plan = AUDIENCE_PLAN.get(audience)
        if plan is None:
            continue
        targets = sorted(entry.id for entry in enabled if entry.kind in plan.source_kinds)
        extra = [t for t in context_terms if normalise_term(t) != term.normalized_form][:2]
        query_text = f'"{term.text}"' if term.must_quote else term.text
        if extra:
            query_text = " ".join([query_text, *extra])
        syntax = (
            QuerySyntax.SITE_SCOPED
            if targets
            else (QuerySyntax.PHRASE if term.must_quote else QuerySyntax.PLAIN)
        )
        priority = max(1, min(10, plan.base_priority + round((1.0 - term.weight) * 3)))
        out.append(
            GeneratedQuery(
                id=f"{term_id}:{audience}" if term_id else None,
                query_text=query_text,
                target_source_type=plan.target_source_type,
                target_source_ids=targets,
                expected_evidence_tier=plan.expected_tier,
                language=term.language,
                syntax=syntax,
                date_from=date_from,
                date_to=date_to,
                additional_terms=extra,
                priority=priority,
                rationale=plan.rationale,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Optional model expansion
# ---------------------------------------------------------------------------

#: Schema for the one job a model does better than a rule here: guessing what a
#: document is *called* in public, which by definition is not in the document.
#: Everything it returns is marked ``model_expansion`` and weighted accordingly.
LLM_VOCABULARY_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "common_names": {"type": "array", "items": {"type": "string"}},
        "political_terminology": {"type": "array", "items": {"type": "string"}},
        "synonyms": {"type": "array", "items": {"type": "string"}},
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "language": {"type": "string"},
                },
                "required": ["text", "language"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["common_names", "political_terminology", "synonyms", "translations"],
    "additionalProperties": False,
}

_EXPANSION_PROMPT: Final[str] = """\
You are building a RETRIEVAL vocabulary for one policy document. The goal is
recall: find everything published about it, from every direction, including
framings you would not use yourself.

Document title: {title}
Short title: {short_title}
Formal identifiers: {identifiers}
Document type: {document_type}
Language: {language}
Key phrases from the text: {phrases}
Named parties: {actors}

Return, as JSON only:
- common_names: short names this document is likely to be referred to by in
  public discussion, in {language}.
- political_terminology: contested phrasings in circulation around this subject,
  from ALL sides of the debate. These are collected to widen retrieval, never to
  endorse or to filter. Include phrasings you consider tendentious.
- synonyms: alternative phrasings and near-equivalents.
- translations: the document's subject rendered in these languages: {targets}.

Rules: no personal names of individuals; no invented identifiers or numbers; each
entry under 90 characters; return only search terms, never sentences.
"""


def _expand_with_provider(
    provider: CompletionProvider,
    document: DocumentModel,
    *,
    phrases: Sequence[str],
    actors: Sequence[str],
    target_languages: Sequence[str],
) -> dict[str, list[tuple[str, str]]]:
    """Ask a model for the names that are not in the document.

    Failure is silent by design: a provider that is down, slow or malformed
    yields an empty expansion and the corresponding category is reported in
    ``known_gaps``. The alternative — failing the phase — would make retrieval
    breadth depend on an endpoint, and a run that crashes produces no vocabulary
    at all, which is strictly worse than a documented gap.
    """
    prompt = _EXPANSION_PROMPT.format(
        title=document.identity.title,
        short_title=document.identity.short_title or "—",
        identifiers=", ".join(
            [document.identity.legislative_identifier or ""]
            + [i.value for i in document.identity.identifiers]
        ).strip(", ")
        or "—",
        document_type=document.identity.document_type,
        language=document.identity.language,
        phrases="; ".join(phrases[:12]) or "—",
        actors="; ".join(actors[:12]) or "—",
        targets=", ".join(target_languages) or "—",
    )
    try:
        raw = provider.complete(prompt, schema=LLM_VOCABULARY_SCHEMA)
    except Exception:  # noqa: BLE001 - an unavailable provider is an ordinary event
        return {}

    payload: Any = raw
    if hasattr(payload, "parsed"):
        parsed = getattr(payload, "parsed", None)
        payload = parsed if parsed is not None else getattr(payload, "text", "")
    if isinstance(payload, str):
        text = payload.strip()
        fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fenced:
            text = fenced.group(1)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}
    if not isinstance(payload, Mapping):
        return {}

    language = document.identity.language
    out: dict[str, list[tuple[str, str]]] = {}
    for key in ("common_names", "political_terminology", "synonyms"):
        values = payload.get(key)
        if isinstance(values, list):
            out[key] = [
                (_WS_RE.sub(" ", str(v)).strip(), language)
                for v in values[:20]
                if str(v).strip() and len(str(v)) <= 90
            ]
    translations = payload.get("translations")
    if isinstance(translations, list):
        out["translations"] = [
            (_WS_RE.sub(" ", str(t.get("text"))).strip(), str(t.get("language")))
            for t in translations[:20]
            if isinstance(t, Mapping) and str(t.get("text", "")).strip()
        ]
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _TermDraft:
    text: str
    language: str
    source: TermSource
    set_name: str
    occurrences: int = 1
    derived_from: str | None = None
    span: Span | None = None
    ambiguity_note: str | None = None


class _VocabularyBuilder:
    """Mines terms, resolves duplicates, then attaches queries to what survives."""

    def __init__(
        self,
        document: DocumentModel,
        *,
        graph: TopicGraph | None,
        registry: Sequence[SourceRegistryEntry],
        target_languages: Sequence[str],
        contested_terms: Sequence[str],
        profile: LinguisticProfile,
    ) -> None:
        self.document = document
        self.graph = graph
        self.registry = list(registry)
        self.target_languages = list(target_languages)
        self.contested_terms = list(contested_terms)
        self.profile = profile
        self.language = document.identity.language
        self.drafts: dict[str, _TermDraft] = {}
        self.notes: list[str] = []

    # -- collection ---------------------------------------------------------

    def add(
        self,
        text: str,
        *,
        source: TermSource,
        set_name: str,
        language: str | None = None,
        occurrences: int = 1,
        derived_from: str | None = None,
        span: Span | None = None,
        ambiguity_note: str | None = None,
    ) -> None:
        """Register one candidate term, keeping the more informative duplicate.

        Duplicates are resolved by set precedence rather than by arrival order,
        so a number that also appears in a heading is filed as an identifier
        regardless of which miner ran first — and the vocabulary does not change
        shape when a miner is reordered.
        """
        cleaned = _clean_term(text)
        if len(cleaned) < 2 or len(cleaned) > 120:
            return
        key = normalise_term(cleaned)
        if not key:
            return
        existing = self.drafts.get(key)
        if existing is not None:
            existing.occurrences += occurrences
            if _SET_PRECEDENCE.index(set_name) < _SET_PRECEDENCE.index(existing.set_name):
                existing.set_name = set_name
                existing.source = source
                existing.text = cleaned
                existing.derived_from = derived_from or existing.derived_from
                existing.span = span or existing.span
            return
        self.drafts[key] = _TermDraft(
            text=cleaned,
            language=language or self.language,
            source=source,
            set_name=set_name,
            occurrences=occurrences,
            derived_from=derived_from,
            span=span,
            ambiguity_note=ambiguity_note,
        )

    def collect(self, provider: CompletionProvider | None) -> None:
        identity = self.document.identity

        # --- official names -------------------------------------------------
        self.add(identity.title, source=TermSource.TITLE, set_name="official_names")
        if identity.subtitle:
            self.add(
                f"{identity.title} {identity.subtitle}",
                source=TermSource.TITLE,
                set_name="official_names",
            )
            self.add(identity.subtitle, source=TermSource.TITLE, set_name="official_names")

        # --- common names ---------------------------------------------------
        if identity.short_title:
            self.add(identity.short_title, source=TermSource.TITLE, set_name="common_names")
        for candidate in _title_short_forms(identity.title, self.profile):
            self.add(candidate, source=TermSource.TITLE, set_name="common_names")
        if identity.document_type_raw and identity.legislative_identifier:
            self.add(
                f"{identity.document_type_raw} {identity.legislative_identifier}",
                source=TermSource.IDENTIFIER,
                set_name="common_names",
            )

        # --- identifiers ----------------------------------------------------
        formal: list[tuple[str, str]] = []
        if identity.legislative_identifier:
            formal.append(("legislative_identifier", identity.legislative_identifier))
        formal.extend((entry.scheme, entry.value) for entry in identity.identifiers)
        if identity.version:
            formal.append(("version", identity.version))
        for scheme, value in formal:
            for variant in identifier_variants(value):
                self.add(
                    variant,
                    source=TermSource.IDENTIFIER,
                    set_name="identifiers",
                    derived_from=scheme,
                    ambiguity_note=(
                        "A bare number collides with unrelated usages; combine it with a "
                        "name term when the source allows."
                        if not re.search(r"[A-Za-z]", variant) and len(variant) <= 6
                        else None
                    ),
                )

        # --- abbreviations --------------------------------------------------
        for acronym, expansion in mine_abbreviations(self.document):
            self.add(
                acronym,
                source=TermSource.ABBREVIATION_EXPANSION,
                set_name="abbreviations",
                derived_from=expansion,
                ambiguity_note=(
                    "Short acronyms collide across domains; results will need filtering."
                    if len(acronym) <= 3
                    else None
                ),
            )
            self.add(
                expansion,
                source=TermSource.ABBREVIATION_EXPANSION,
                set_name="official_names",
                derived_from=acronym,
            )

        # --- provision names ------------------------------------------------
        for provision in sorted(self.document.provisions, key=lambda p: p.id):
            if provision.title:
                self.add(
                    provision.title,
                    source=TermSource.PROVISION_HEADING,
                    set_name="provision_names",
                    derived_from=provision.id,
                    span=provision.span,
                )
        stack = list(self.document.structure.sections)
        while stack:
            section = stack.pop()
            self.add(
                section.heading,
                source=TermSource.HEADING,
                set_name="provision_names",
                derived_from=section.id,
            )
            stack.extend(section.children)

        # --- technical terminology ------------------------------------------
        for definition in sorted(self.document.definitions, key=lambda d: d.id):
            self.add(
                definition.term,
                source=TermSource.DEFINITION,
                set_name="technical_terminology",
                derived_from=definition.id,
                span=definition.span,
                ambiguity_note=(
                    "The document defines this term for its own purposes; general usage "
                    "may differ and results will need filtering."
                ),
            )
        for keyword in identity.keywords:
            self.add(keyword, source=TermSource.MANUAL, set_name="technical_terminology")
        phrases = mine_phrases(_document_corpus(self.document), self.profile)
        for phrase, count in phrases:
            self.add(
                phrase,
                source=TermSource.HEADING,
                set_name="technical_terminology",
                occurrences=count,
            )

        # --- sector terminology ---------------------------------------------
        for industry in sorted(self.document.affected_industries, key=lambda i: i.id):
            self.add(
                industry.label,
                source=TermSource.ENTITY,
                set_name="sector_terminology",
                derived_from=industry.id,
                span=industry.span,
            )
        for population in sorted(self.document.affected_populations, key=lambda p: p.id):
            self.add(
                population.label,
                source=TermSource.ENTITY,
                set_name="sector_terminology",
                derived_from=population.id,
                span=population.span,
            )

        # --- actor terms (roles and bodies only, never individuals) ----------
        if identity.institution:
            self.add(identity.institution, source=TermSource.ENTITY, set_name="actor_terms")
        for institution in sorted(self.document.affected_institutions, key=lambda i: i.id):
            self.add(
                institution.name,
                source=TermSource.ENTITY,
                set_name="actor_terms",
                derived_from=institution.id,
                span=institution.span,
            )
        for authorship in identity.authorship:
            if authorship.is_personal_name:
                # A personal name in the retrieval vocabulary would leak identity
                # into what gets collected, and from there into what gets ranked.
                continue
            self.add(
                authorship.entity or authorship.role,
                source=TermSource.ENTITY,
                set_name="actor_terms",
            )

        # --- from the topic graph -------------------------------------------
        self._collect_from_graph()

        # --- caller-supplied contested vocabulary ----------------------------
        for term in self.contested_terms:
            self.add(term, source=TermSource.MANUAL, set_name="political_terminology")

        # --- mechanical synonyms ---------------------------------------------
        self._mechanical_synonyms()

        # --- optional model expansion ----------------------------------------
        if provider is not None:
            self._model_expansion(provider, phrases)

    def _collect_from_graph(self) -> None:
        """Pull entity names and their aliases out of phase 3.

        The graph has already merged spellings, so its aliases are exactly the
        alternative surface forms coverage of an entity is likely to be published
        under — the highest-value terms Aleph can get without guessing.
        """
        if self.graph is None:
            return
        set_by_kind = {
            "institution": "actor_terms",
            "person_role": "actor_terms",
            "company": "actor_terms",
            "sector": "sector_terminology",
            "social_group": "sector_terminology",
            "region": "sector_terminology",
            "tax": "technical_terminology",
            "benefit": "technical_terminology",
            "right": "technical_terminology",
            "obligation": "technical_terminology",
            "policy": "common_names",
        }
        for node in sorted(self.graph.nodes, key=lambda n: n.id):
            set_name = set_by_kind.get(node.kind.value)
            if set_name is None:
                continue
            weight_hint = 1 + int(round((node.salience or 0.0) * 4))
            self.add(
                node.label,
                source=TermSource.ENTITY,
                set_name=set_name,
                occurrences=weight_hint,
                derived_from=node.id,
            )
            for alias in node.aliases:
                # An alias is by definition an alternative phrasing, and the
                # graph has already established that it names the same entity —
                # which makes it exactly what the synonyms set is for. Coverage
                # of an entity is routinely published under a name the document
                # never uses, and these are the names Aleph actually has evidence
                # for rather than guesses at.
                self.add(
                    alias,
                    source=TermSource.ENTITY,
                    set_name="synonyms",
                    derived_from=node.id,
                )

    def _mechanical_synonyms(self) -> None:
        """Orthographic variants that a strict index would otherwise miss.

        Not linguistics: hyphenation and bracketing are typesetting choices, and
        a term written one way in the source is written the other way in a
        headline. Accent-stripped spellings are deliberately *not* generated
        here — every term already carries ``normalized_form``, which is
        accent-folded, so a provider that needs the unaccented spelling has it
        without the vocabulary double-counting one name as two.
        """
        for draft in sorted(self.drafts.values(), key=lambda d: d.text)[:]:
            if draft.set_name not in {
                "official_names",
                "common_names",
                "abbreviations",
                "technical_terminology",
            }:
                continue
            if "-" in draft.text:
                self.add(
                    draft.text.replace("-", " "),
                    source=TermSource.SYNONYM_EXPANSION,
                    set_name="synonyms",
                    derived_from=draft.text,
                )
            stem, parentheticals = _split_parenthetical(draft.text)
            if parentheticals and stem:
                self.add(
                    stem,
                    source=TermSource.SYNONYM_EXPANSION,
                    set_name="synonyms",
                    derived_from=draft.text,
                )

    def _model_expansion(
        self, provider: CompletionProvider, phrases: Sequence[tuple[str, int]]
    ) -> None:
        actors = [d.text for d in self.drafts.values() if d.set_name == "actor_terms"]
        expansion = _expand_with_provider(
            provider,
            self.document,
            phrases=[p for p, _ in phrases],
            actors=sorted(actors),
            target_languages=self.target_languages,
        )
        if not expansion:
            self.notes.append("Model expansion was requested but returned nothing usable.")
            return
        for key, set_name, source in (
            ("common_names", "common_names", TermSource.MODEL_EXPANSION),
            ("political_terminology", "political_terminology", TermSource.MODEL_EXPANSION),
            ("synonyms", "synonyms", TermSource.SYNONYM_EXPANSION),
            ("translations", "synonyms", TermSource.TRANSLATION),
        ):
            for text, language in expansion.get(key, []):
                self.add(
                    text,
                    source=source,
                    set_name=set_name,
                    language=language,
                    ambiguity_note=(
                        "Generated rather than lifted from the document; treat retrieval "
                        "built on this term as weaker."
                    ),
                )
        self.notes.append(
            "Common names, contested vocabulary and translations were expanded by a "
            "language model and are marked as generated."
        )

    # -- assembly -----------------------------------------------------------

    def build(self, *, generated_at: str | None, max_query_terms: int) -> SearchVocabulary:
        buckets: dict[str, list[_TermDraft]] = {name: [] for name in TERM_SET_NAMES}
        for key in sorted(self.drafts):
            draft = self.drafts[key]
            buckets[draft.set_name].append(draft)

        dates = self.document.identity.dates
        date_from = (dates.introduced or dates.published) if dates else None

        term_sets_kwargs: dict[str, list[VocabularyTerm]] = {}
        for set_name in TERM_SET_NAMES:
            drafts = sorted(
                buckets[set_name],
                key=lambda d: (
                    -term_weight(d.text, d.source, occurrences=d.occurrences),
                    normalise_term(d.text),
                ),
            )
            terms: list[VocabularyTerm] = []
            for index, draft in enumerate(drafts):
                weight = term_weight(
                    draft.text,
                    draft.source,
                    occurrences=draft.occurrences,
                    ambiguous=draft.ambiguity_note is not None,
                )
                term_id = f"{set_name}:{index:03d}"
                term = VocabularyTerm(
                    id=term_id,
                    text=draft.text,
                    language=draft.language,
                    weight=weight,
                    source=draft.source,
                    normalized_form=normalise_term(draft.text),
                    must_quote=len(_TOKEN_RE.findall(draft.text)) > 1,
                    ambiguity_note=draft.ambiguity_note,
                    derived_from=draft.derived_from,
                    span=draft.span,
                )
                if index < max_query_terms:
                    term = term.model_copy(
                        update={
                            "generated_queries": generate_queries(
                                term,
                                audiences=SET_AUDIENCES.get(set_name, (QueryAudience.OPEN_WEB,)),
                                registry=self.registry,
                                date_from=date_from,
                                term_id=term_id,
                                context_terms=self._context_terms(set_name),
                            )
                        }
                    )
                terms.append(term)
            term_sets_kwargs[set_name] = terms

        gaps = _known_gaps(term_sets_kwargs, has_registry=bool(self.registry))
        expansion_notes = " ".join(
            [
                f"Terms mined from the document with segmentation profile '{self.profile.code}'; "
                "identifiers permuted mechanically; abbreviations detected from the document's "
                "own 'Long Name (LN)' introductions.",
                *self.notes,
            ]
        )
        return SearchVocabulary(
            schema_version=SCHEMA_VERSION,
            data_status=self.document.data_status or DataStatus.DERIVED,
            document_id=self.document.id,
            generated_at=generated_at,
            primary_language=self.language,
            target_languages=sorted({self.language, *self.target_languages}),
            term_sets=TermSets(**term_sets_kwargs),
            expansion_notes=expansion_notes,
            known_gaps=gaps,
        )

    def _context_terms(self, set_name: str) -> list[str]:
        """Disambiguators attached to terms that would otherwise return noise.

        A bare file number or a one-word sector name matches thousands of
        unrelated documents. Pairing it with the instrument's short name narrows
        recall on purpose — and only for the sets where the term alone is known
        to be ambiguous.
        """
        if set_name not in {"identifiers", "sector_terminology", "abbreviations"}:
            return []
        identity = self.document.identity
        anchor = identity.short_title or identity.title
        return [anchor] if anchor else []


_PARENTHETICAL_RE: Final[re.Pattern[str]] = re.compile(r"\s*[(\[]([^()\[\]]{1,80})[)\]]")


def _split_parenthetical(text: str) -> tuple[str, list[str]]:
    """Split ``Name (Alias)`` into the bare name and its bracketed forms."""
    aliases = [m.group(1).strip() for m in _PARENTHETICAL_RE.finditer(text)]
    stem = _WS_RE.sub(" ", _PARENTHETICAL_RE.sub(" ", text)).strip()
    return stem, [a for a in aliases if a]


def _title_short_forms(title: str, profile: LinguisticProfile) -> list[str]:
    """Derive plausible short names from a formal title, mechanically.

    Formal titles are built as "<instrument type> that <does something>", and the
    part after the connective is what people actually say. Splitting on the
    document's own punctuation and taking the leading noun phrase recovers a
    usable short name without a model and without a topic list. These are
    candidates for recall, not assertions about what the document is called.
    """
    out: list[str] = []
    cleaned = _WS_RE.sub(" ", title).strip()
    for part in re.split(r"[:—–\-–]{1,2}|,", cleaned):
        part = part.strip()
        if 8 <= len(part) < len(cleaned):
            out.append(part)
    tokens = cleaned.split()
    if len(tokens) > 5:
        head = " ".join(tokens[:5])
        while head and _fold(head.split()[-1]) in profile.stopwords:
            head = " ".join(head.split()[:-1])
        if len(head) >= 8:
            out.append(head)
    if len(tokens) > 7:
        # The substantive part of a formal title is at the end: "<instrument>
        # that <does the thing>". Leading function words are trimmed so the
        # result begins on a content word rather than mid-phrase.
        tail_tokens = tokens[-6:]
        while tail_tokens and _fold(tail_tokens[0]) in profile.stopwords:
            tail_tokens.pop(0)
        tail = " ".join(tail_tokens)
        if len(tail) >= 10:
            out.append(tail)
    return out


def _known_gaps(
    term_sets: Mapping[str, Sequence[VocabularyTerm]], *, has_registry: bool
) -> list[str]:
    """Name the categories that came up empty.

    Published because an unpopulated category is a retrieval risk that readiness
    scoring reads directly. ``common_names`` is the one that matters most: it is
    usually the highest-recall group and is rarely present in the document
    itself, so an empty one is a warning that the search will systematically
    under-collect and that the resulting quiet must not be read as an absence of
    coverage.
    """
    explanations = {
        "official_names": "no formal title could be read from the document",
        "common_names": (
            "no short name in public circulation was found; retrieval will rely on the "
            "formal title and will systematically under-collect"
        ),
        "identifiers": (
            "no formal number or code was found; the primary record may be unreachable "
            "by identifier and only findable by name"
        ),
        "abbreviations": "the document introduces no short forms of its own",
        "political_terminology": (
            "no contested vocabulary was supplied or generated; Aleph will not invent "
            "political phrasings, so all sides of a debate may not be reachable"
        ),
        "technical_terminology": "no defined terms or repeated technical phrases were found",
        "sector_terminology": "the document names no industry or affected group",
        "synonyms": "no alternative phrasings were derived",
        "provision_names": "no provision or section headings were available",
        "actor_terms": "the document names no institution or role",
    }
    gaps = [f"{name}: {explanations[name]}" for name in TERM_SET_NAMES if not term_sets.get(name)]
    if not has_registry:
        gaps.append(
            "source_registry: no registry entries were supplied, so no query could be "
            "routed to a named source; only open-web queries were generated"
        )
    return gaps


def build_search_vocabulary(
    document: DocumentModel,
    *,
    graph: TopicGraph | None = None,
    registry: Sequence[SourceRegistryEntry] = (),
    target_languages: Sequence[str] = (),
    contested_terms: Sequence[str] = (),
    provider: CompletionProvider | None = None,
    generated_at: str | None = None,
    profile: LinguisticProfile | None = None,
    max_query_terms: int = 8,
) -> SearchVocabulary:
    """Run warm phase 4 over a document.

    Works with no model, no network and no registry: the deterministic miners
    alone produce identifiers, official names, abbreviations, provision names,
    technical phrases, sector and actor terms for a document in any language,
    including one Aleph has no linguistic profile for.

    Args:
        document: The phase-1 reading.
        graph: Phase-3 output. Supplying it adds resolved entity names and their
            merged aliases, which are the alternative spellings coverage is
            actually published under.
        registry: Sources queries may be routed to. Without it, only open-web
            queries are generated and that limitation is recorded in
            ``known_gaps`` rather than passed over.
        target_languages: Extra languages retrieval should be attempted in.
        contested_terms: Caller-supplied contested vocabulary. Aleph does not
            invent political phrasings; where none is supplied and no model is
            configured, ``political_terminology`` stays empty and says so.
        provider: Optional language model, used only to guess the names a
            document is known by in public — which by definition are not in it.
            Everything it returns is marked ``model_expansion``.
        generated_at: UTC timestamp. ``None`` by default so runs are byte-identical.
        profile: Override language detection.
        max_query_terms: How many terms per set get concrete queries attached.
            Queries are the expensive part; the terms themselves are all kept.

    Returns:
        A :class:`~aleph.core.models.SearchVocabulary` with all ten term sets
        present — empty where nothing was found, and named in ``known_gaps``.
    """
    resolved_profile = profile or profile_for_text(
        "\n".join(_document_corpus(document)[:60]) or document.identity.title,
        document.identity.language,
    )
    builder = _VocabularyBuilder(
        document,
        graph=graph,
        registry=registry,
        target_languages=target_languages or document.identity.additional_languages,
        contested_terms=contested_terms,
        profile=resolved_profile or GENERIC_PROFILE,
    )
    builder.collect(provider)
    return builder.build(generated_at=generated_at, max_query_terms=max_query_terms)
