"""The eight framing dimensions, each computed by an explicit, readable function.

Framing analysis is the part of Aleph most easily turned into a weapon, so this
module is built to make that hard. The failure mode is not a wrong number; it is
a number that *cannot be argued with* — a dial reading 72 with nothing behind it,
which a reader can only accept or reject wholesale. Every function here therefore
returns a :class:`DimensionResult` carrying the sentences it examined, the terms
it matched, the counts, the formula that turned them into a score, the
uncertainties it could not resolve, and the observations that point the other
way. The score is a summary of that record, never a substitute for it.

**There is no aggregate and none can be computed.** ``FramingAnalysis`` exposes
eight results and no ninth. Six dimensions are ``lower_is_better`` and two are
``higher_is_better``; averaging them would add a merit to a fault, and the result
would be read as a left-right placement, which Aleph does not emit.

**Nothing here reads identity.** No function in this module takes an outlet, an
author, a party or a speaker name as an input to a score. ``speaker_role``
appears only where the *count of distinct roles* is the measurement itself
(source diversity), and roles are counted, never ranked.

**Each dimension is measured against something external, not against taste.**

===============================  ==========================================
dimension                        measured against
===============================  ==========================================
``selection_asymmetry``          the figures, provisions and voices the
                                 primary document and the cluster actually
                                 contain
``loaded_language``              a module-level lexicon of evaluative terms,
                                 with charged words *inside quotations*
                                 discounted, because quoting a speaker's word
                                 is not adopting it
``context_omission``             the propositions the rest of the cluster
                                 reported — computed against peers, never in
                                 isolation
``certainty_inflation``          the modality of the underlying evidence: the
                                 evidence says "estimates", the article says
                                 "will"
``unsupported_causal_language``  whether each causal connective's claim is
                                 backed by an evidence item
``opinion_as_fact``              whether evaluative predicates carry
                                 attribution or a stance marker
``source_diversity``             distinct *independent* sources, collapsed
                                 through :class:`IndependenceAnalysis`
``primary_source_grounding``     the fraction of factual claims traceable to
                                 a primary document
===============================  ==========================================

**Component sign convention.** Every component's ``weight`` is the number of
score points it contributed, and ``direction`` is the sign of that weight:
``positive`` raised the score, ``negative`` lowered it, ``none`` is
informational. The components of a dimension sum to its score. Whether raising
is good or bad is carried by the dimension's ``polarity`` and by nothing else —
a component never asserts that something is a fault.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from aleph.core.enums import (
    ArticleType,
    ConfidenceEffect,
    ConfidenceFactor,
    Direction,
    EvidenceTier,
    FramingDimensionKey,
    GroundingKind,
    Modality,
    MonetaryRole,
    Polarity,
    PropositionType,
    StatementType,
    UncertaintyKind,
)
from aleph.core.models import (
    Claim,
    Component,
    Confidence,
    ConfidenceBasis,
    EvidenceItem,
    FramingDimension,
    FramingDimensionHigherIsBetter,
    FramingDimensionLowerIsBetter,
    FramingDimensions,
    FramingProfile,
    IndependenceAnalysis,
    MonetaryValue,
    NewsArticle,
    NewsCluster,
    Proposition,
    Provision,
    Uncertainty,
)

__all__ = [
    "CAUSAL_CUES",
    "DIMENSION_POLARITY",
    "LOADED_LANGUAGE_LEXICON",
    "MODALITY_CUES",
    "PROFILE_VERSION",
    "ArticleUnderAnalysis",
    "Calculation",
    "CausalCue",
    "ContextCandidate",
    "DimensionResult",
    "FramingAnalysis",
    "FramingContext",
    "LoadedTerm",
    "LoadedTermCategory",
    "ModalityCue",
    "SentenceRef",
    "SourceStatement",
    "analyse_framing",
    "build_context_candidates",
    "build_source_statements",
    "certainty_of",
    "resolve_independence",
    "score_certainty_inflation",
    "score_context_omission",
    "score_loaded_language",
    "score_opinion_as_fact",
    "score_primary_source_grounding",
    "score_selection_asymmetry",
    "score_source_diversity",
    "score_unsupported_causal_language",
    "split_sentences",
]

#: Version of this analyser. A framing score is only interpretable alongside the
#: version that produced it, so it is stamped on every profile.
PROFILE_VERSION: Final[str] = "aleph-framing/1.0.0"


# ---------------------------------------------------------------------------
# Text handling
#
# Everything below matches on *folded* text: NFKD-decomposed, combining marks
# dropped, lowercased. Folding means "económico" and "economico" are one token,
# which matters because news copy is inconsistently accented and a lexicon that
# missed unaccented spellings would systematically under-report exactly the
# outlets that type fastest.
# ---------------------------------------------------------------------------


def fold(text: str) -> str:
    """Return ``text`` lowercased with accents and combining marks removed."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


#: Abbreviations that end in a period without ending a sentence. Kept short and
#: language-generic: an over-long list costs nothing, a missing entry splits a
#: sentence in half and mis-attributes every term in the second half.
_ABBREVIATIONS: Final[frozenset[str]] = frozenset(
    {
        "art",
        "arts",
        "aprox",
        "cap",
        "cf",
        "cfr",
        "co",
        "dr",
        "dra",
        "ed",
        "eds",
        "eg",
        "etc",
        "fig",
        "ie",
        "inc",
        "ing",
        "lic",
        "ltd",
        "ltda",
        "min",
        "mr",
        "mrs",
        "ms",
        "n",
        "no",
        "nro",
        "num",
        "p",
        "pag",
        "pp",
        "prof",
        "sa",
        "sr",
        "sra",
        "srta",
        "st",
        "ud",
        "uds",
        "vs",
    }
)

_SENTENCE_BOUNDARY = re.compile(r'([.!?…]+)(["\'»”’\)]*)(\s+)')
_WORD_BEFORE_STOP = re.compile(r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s*$")
_OPENS_SENTENCE = re.compile(r"^[\"'«“¿¡\(\[]*[A-ZÁÉÍÓÚÜÑ0-9]")


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    """Split ``text`` into ``(char_start, char_end, sentence)`` triples.

    Offsets are preserved because a framing finding must be locatable in the
    article a reader is looking at; a bare list of sentences would make every
    component unverifiable by hand.

    The splitter is conservative: it breaks only when a terminal punctuation
    mark is followed by whitespace and something that looks like the start of a
    new sentence, and it refuses to break after a known abbreviation. Spanish
    inverted marks (``¿``, ``¡``) count as sentence openers.
    """
    if not text or not text.strip():
        return []

    spans: list[tuple[int, int, str]] = []
    start = 0
    for match in _SENTENCE_BOUNDARY.finditer(text):
        end = match.end(2)
        head = text[start:end]
        prior = _WORD_BEFORE_STOP.search(text[start : match.start(1)])
        if prior is not None and fold(prior.group(1)) in _ABBREVIATIONS:
            continue
        if not _OPENS_SENTENCE.match(text[match.end() :]):
            continue
        if head.strip():
            spans.append((start, end, head.strip()))
        start = match.end()

    tail = text[start:]
    if tail.strip():
        spans.append((start, start + len(tail), tail.strip()))
    return spans


_QUOTE_SPAN = re.compile(r"[\"«“](.+?)[\"»”]", re.DOTALL)
_TOKEN = re.compile(r"[a-z0-9]+")

#: Function words carrying no topical content in either supported language.
#: Used only to decide whether two passages are *about* the same thing; nothing
#: downstream branches on the language of an article.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    """
    a al algo algun alguna algunas alguno algunos ante antes aquel aquella aquello aqui asi aun
    aunque cada como con contra cual cuales cuando cuanto de del desde donde dos el ella ellas
    ello ellos en entre era eran eres es esa esas ese eso esos esta estan estas este esto estos
    fue fueron ha haber habia han hasta hay la las le les lo los mas me mi mientras muy nada ni
    no nos nuestra nuestro o os otra otras otro otros para pero poco por porque que quien quienes
    se sea segun ser si sin sobre solo son su sus tambien tanto te tiene tienen toda todas todo
    todos tras tu un una unas uno unos ya yo
    about after all also am an and any are as at be because been before being between both but
    by can could did do does for from had has have he her hers him his how if in into is it its
    more most no nor not of on once only or other our out over own same she should so some such
    than that the their them then there these they this those through to too under until up very
    was we were what when where which while who whom why will with would you your
    """.split()
)


def content_terms(folded_text: str, *, min_length: int = 4) -> frozenset[str]:
    """Return the topical tokens of already-folded text.

    Short tokens and function words are dropped so that "the levy rises in 2027"
    and "the levy will rise in 2027" are recognised as being about the same
    thing, which is what every cross-text match in this module needs.
    """
    return frozenset(
        token
        for token in _TOKEN.findall(folded_text)
        if len(token) >= min_length and token not in _STOPWORDS
    )


_NUMBER = re.compile(r"\d[\d.,]*")


def normalise_number(token: str) -> str:
    """Reduce one numeral to a separator-independent canonical form.

    ``1.234,5``, ``1,234.5`` and ``1234.5`` all become ``"1234.5"``. Both
    conventions must be handled because Aleph is document-agnostic and the same
    analysis routinely spans sources that group thousands differently.

    Where a single separator is genuinely ambiguous the heuristic is stated
    rather than hidden: groups of exactly three digits after the first are read
    as thousands, unless the leading group is ``0`` or starts with ``0``, in
    which case the separator is a decimal mark. ``12.345`` therefore reads as
    twelve thousand three hundred and forty-five. This can be wrong; it is used
    only to *pair* an article sentence with a source statement, never to
    re-state a figure, so a mispairing costs a comparison rather than corrupting
    a published number.
    """
    dots, commas = token.count("."), token.count(",")
    decimal_sep: str | None
    if dots and commas:
        decimal_sep = "." if token.rfind(".") > token.rfind(",") else ","
    elif dots or commas:
        sep = "." if dots else ","
        groups = token.split(sep)
        looks_like_thousands = (
            len(groups) > 1
            and all(len(group) == 3 for group in groups[1:])
            and bool(groups[0])
            and not groups[0].startswith("0")
        )
        decimal_sep = None if looks_like_thousands else sep
    else:
        decimal_sep = None

    if decimal_sep is None:
        whole, frac = re.sub(r"\D", "", token), ""
    else:
        head, _, frac = token.rpartition(decimal_sep)
        whole = re.sub(r"\D", "", head)
    whole = whole.lstrip("0") or "0"
    frac = re.sub(r"\D", "", frac).rstrip("0")
    return f"{whole}.{frac}" if frac else whole


def numeric_tokens(text: str) -> frozenset[str]:
    """Return the canonicalised numbers appearing in ``text``.

    Numbers are the strongest cross-text anchor available without a language
    model: an article sentence and an evidence statement that share a figure are
    almost always about the same quantity, and that is precisely the pairing
    ``certainty_inflation`` needs in order to compare their modality.
    """
    tokens = set()
    for raw in _NUMBER.findall(text):
        cleaned = raw.strip(".,")
        if cleaned:
            tokens.add(normalise_number(cleaned))
    return frozenset(tokens)


def overlap(left: frozenset[str], right: frozenset[str]) -> float:
    """Return the Szymkiewicz–Simpson overlap of two term sets, in ``[0,1]``.

    Overlap rather than Jaccard because the two texts are of very different
    lengths: a one-clause evidence statement and a forty-word news sentence can
    be about the same thing while sharing only a small fraction of their union.
    """
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


# ---------------------------------------------------------------------------
# Sentence records
# ---------------------------------------------------------------------------


class Zone(StrEnum):
    """Where in an article a sentence sits.

    Zone matters because readership does not distribute evenly: a charged word
    in a headline reaches everyone who scrolls past, and one in paragraph
    nineteen reaches the few who finish. Weighting by zone is a fact about
    exposure, not a judgement about the outlet.
    """

    HEADLINE = "headline"
    DEK = "dek"
    BODY = "body"
    NEUTRAL_SUMMARY = "neutral_summary"


#: Exposure multipliers by zone, applied wherever a dimension counts occurrences.
ZONE_WEIGHT: Final[Mapping[Zone, float]] = {
    Zone.HEADLINE: 1.5,
    Zone.DEK: 1.2,
    Zone.BODY: 1.0,
    Zone.NEUTRAL_SUMMARY: 0.0,
}


@dataclass(frozen=True, slots=True)
class SentenceRef:
    """One sentence of an article, with everything a dimension needs to cite it.

    ``in_quotation`` is load-bearing across several dimensions: material inside
    quotation marks is the *speaker's* wording reproduced, which is a different
    editorial act from the outlet choosing that word in its own voice. Aleph
    discounts rather than exempts it, because a wholly quote-built article can
    still be framed by which quotes were chosen.
    """

    index: int
    text: str
    folded: str
    zone: Zone
    char_start: int
    char_end: int
    in_quotation: bool
    terms: frozenset[str]
    numbers: frozenset[str]

    @property
    def weight(self) -> float:
        """Exposure weight of this sentence."""
        return ZONE_WEIGHT[self.zone]


def _sentences_from(text: str, zone: Zone, offset: int, start_index: int) -> list[SentenceRef]:
    quoted: list[tuple[int, int]] = [(m.start(1), m.end(1)) for m in _QUOTE_SPAN.finditer(text)]
    out: list[SentenceRef] = []
    for i, (start, end, sentence) in enumerate(split_sentences(text)):
        inside = any(qs <= start and end <= qe + 1 for qs, qe in quoted) or (
            sentence.startswith(('"', "«", "“")) and sentence.rstrip().endswith(('"', "»", "”"))
        )
        folded = fold(sentence)
        out.append(
            SentenceRef(
                index=start_index + i,
                text=sentence,
                folded=folded,
                zone=zone,
                char_start=offset + start,
                char_end=offset + end,
                in_quotation=inside,
                terms=content_terms(folded),
                numbers=numeric_tokens(sentence),
            )
        )
    return out


# ---------------------------------------------------------------------------
# The loaded-language lexicon
#
# IDENTITY-FREE BY CONSTRUCTION. Every entry is a common evaluative word or
# fixed phrase. There is no party name, no politician's name, no institution and
# no jurisdiction anywhere in this table, and _validate_lexicon() refuses to let
# one in unnoticed. A lexicon that named actors would score an article for *whom*
# it wrote about rather than *how*, which is the precise substitution Aleph
# exists to refuse.
#
# Entries are also symmetric: for every charged word that disparages a measure
# there is one that celebrates it, and both score. An analyser that only knew
# hostile vocabulary would report enthusiasm as neutrality.
# ---------------------------------------------------------------------------


class LoadedTermCategory(StrEnum):
    """Why a term is evaluative. Rhetorical categories only — never actors.

    The category is published with every match so a reader can see the *kind* of
    charge being alleged: a catastrophe metaphor and an intensifying adverb are
    both loaded, and conflating them would make the score unarguable.
    """

    CATASTROPHE = "catastrophe"
    """Framing an outcome as disaster or ruin."""
    CELEBRATION = "celebration"
    """Framing an outcome as triumph or salvation."""
    MORAL_CHARGE = "moral_charge"
    """Imputing theft, gift, betrayal, generosity — a moral verdict as description."""
    COMBAT_METAPHOR = "combat_metaphor"
    """Describing a policy process as war, attack or assault."""
    INTENSIFIER = "intensifier"
    """Adverbs and adjectives that inflate scale without adding information."""
    IDEOLOGICAL_EPITHET = "ideological_epithet"
    """Epithets applicable to any position — 'radical', 'dogmatic', 'populist'.
    Included because they are charged; excluded from any left-right reading,
    which Aleph does not compute."""
    DELEGITIMISING = "delegitimising"
    """Wording that treats a position as unserious rather than mistaken."""
    ALARM = "alarm"
    """Urgency and threat framing — 'amenaza', 'crisis', 'spiral'."""


@dataclass(frozen=True, slots=True)
class LoadedTerm:
    """One evaluative expression, its charge and a neutral wording that exists.

    ``neutral_alternative`` is required in spirit and in practice: a term is only
    fairly called *loaded* if a neutral description of the same fact was
    available, and naming that alternative is what turns a score into a claim a
    writer can act on or dispute.
    """

    id: str
    forms: tuple[str, ...]
    """Folded surface forms, including inflections. Matched on word boundaries.
    Every form is unique across the whole lexicon, so a match attributes to
    exactly one entry and no sentence is counted twice."""
    language: str
    """BCP-47 tag, or ``'mul'`` where a word is spelled identically in both
    supported languages ('brutal', 'radical'). One entry rather than two keeps
    forms unique and stops a shared word being scored under whichever language
    happened to be listed first."""
    category: LoadedTermCategory
    intensity: float
    """``0 < intensity <= 1``: how much charge the term carries relative to the
    strongest terms in the table."""
    valence: int
    """``+1`` favourable to the measure described, ``-1`` unfavourable. Recorded
    so a reader can see whether an article's charge runs one way; NEVER summed
    into a leaning, and no dimension branches on it."""
    neutral_alternative: str


LOADED_LANGUAGE_LEXICON: Final[tuple[LoadedTerm, ...]] = (
    # -- Spanish, unfavourable ------------------------------------------------
    LoadedTerm(
        "es.desastre",
        ("desastre", "desastres", "desastroso", "desastrosa", "desastrosos", "desastrosas"),
        "es",
        LoadedTermCategory.CATASTROPHE,
        0.9,
        -1,
        "describe the specific outcome and its estimated size",
    ),
    LoadedTerm(
        "es.catastrofico",
        ("catastrofico", "catastrofica", "catastroficos", "catastroficas", "catastrofe"),
        "es",
        LoadedTermCategory.CATASTROPHE,
        1.0,
        -1,
        "state the projected magnitude and its source",
    ),
    LoadedTerm(
        "es.ruinoso",
        ("ruinoso", "ruinosa", "ruinosos", "ruinosas", "ruina"),
        "es",
        LoadedTermCategory.CATASTROPHE,
        0.85,
        -1,
        "state the projected cost",
    ),
    LoadedTerm(
        "es.saqueo",
        ("saqueo", "saqueos", "saquear", "saquea", "expolio", "expoliar"),
        "es",
        LoadedTermCategory.MORAL_CHARGE,
        1.0,
        -1,
        "name the transfer and who bears it",
    ),
    LoadedTerm(
        "es.despilfarro",
        ("despilfarro", "despilfarros", "despilfarrar", "derroche", "derrochar"),
        "es",
        LoadedTermCategory.MORAL_CHARGE,
        0.85,
        -1,
        "state the spending figure and what it funds",
    ),
    LoadedTerm(
        "es.manotazo",
        ("manotazo", "zarpazo", "mordida", "tijeretazo", "hachazo"),
        "es",
        LoadedTermCategory.COMBAT_METAPHOR,
        0.8,
        -1,
        "state the size of the change",
    ),
    LoadedTerm(
        "es.ataque",
        ("ataque", "ataques", "atacar", "ataca", "arremetida", "embestida", "ofensiva"),
        "es",
        LoadedTermCategory.COMBAT_METAPHOR,
        0.7,
        -1,
        "describe the proposal and the disagreement about it",
    ),
    LoadedTerm(
        "es.amenaza",
        ("amenaza", "amenazas", "amenazar", "amenaza con"),
        "es",
        LoadedTermCategory.ALARM,
        0.6,
        -1,
        "state the risk, its probability and its source",
    ),
    LoadedTerm(
        "es.draconiano",
        ("draconiano", "draconiana", "draconianos", "draconianas"),
        "es",
        LoadedTermCategory.INTENSIFIER,
        0.8,
        -1,
        "state the level of the requirement or penalty",
    ),
    LoadedTerm(
        "mul.brutal",
        ("brutal", "brutales", "brutalmente", "brutally", "salvaje", "salvajes"),
        "mul",
        LoadedTermCategory.INTENSIFIER,
        0.85,
        -1,
        "state the size of the change",
    ),
    LoadedTerm(
        "es.escandaloso",
        ("escandaloso", "escandalosa", "escandalosos", "escandalosas", "escandalo"),
        "es",
        LoadedTermCategory.MORAL_CHARGE,
        0.8,
        -1,
        "state the fact and who disputes it",
    ),
    LoadedTerm(
        "es.improvisado",
        ("improvisado", "improvisada", "improvisacion", "chapucero", "chapucera"),
        "es",
        LoadedTermCategory.DELEGITIMISING,
        0.7,
        -1,
        "describe the drafting timeline and what was consulted",
    ),
    LoadedTerm(
        "es.populista",
        ("populista", "populistas", "populismo", "demagogico", "demagogica", "demagogia"),
        "es",
        LoadedTermCategory.IDEOLOGICAL_EPITHET,
        0.75,
        -1,
        "describe the measure and the objection to it",
    ),
    LoadedTerm(
        "mul.radical",
        ("radical", "radicales", "extremista", "extremistas", "dogmatico", "dogmatica"),
        "mul",
        LoadedTermCategory.IDEOLOGICAL_EPITHET,
        0.65,
        -1,
        "state how far the change departs from current rules",
    ),
    LoadedTerm(
        "es.crisis",
        ("crisis", "colapso", "colapsar", "descalabro", "debacle"),
        "es",
        LoadedTermCategory.ALARM,
        0.65,
        -1,
        "state the indicator and the threshold being crossed",
    ),
    LoadedTerm(
        "es.golpe",
        ("golpe", "golpes", "golpea", "golpear", "castiga", "castigar", "castigo"),
        "es",
        LoadedTermCategory.COMBAT_METAPHOR,
        0.6,
        -1,
        "state who pays and how much",
    ),
    # -- Spanish, favourable --------------------------------------------------
    LoadedTerm(
        "es.historico",
        ("historico", "historica", "historicos", "historicas", "sin precedentes"),
        "es",
        LoadedTermCategory.CELEBRATION,
        0.7,
        1,
        "state what makes it larger or earlier than prior measures",
    ),
    LoadedTerm(
        "es.milagroso",
        ("milagroso", "milagrosa", "milagro", "prodigioso", "prodigiosa"),
        "es",
        LoadedTermCategory.CELEBRATION,
        0.95,
        1,
        "state the projected effect and its source",
    ),
    LoadedTerm(
        "es.valiente",
        ("valiente", "valientes", "audaz", "audaces", "ambicioso", "ambiciosa"),
        "es",
        LoadedTermCategory.CELEBRATION,
        0.6,
        1,
        "state the scale of the change",
    ),
    LoadedTerm(
        "es.regalo",
        ("regalo", "regalos", "regalar", "regala", "dadiva", "dadivas"),
        "es",
        LoadedTermCategory.MORAL_CHARGE,
        0.85,
        -1,
        "name the transfer, its size and its recipients",
    ),
    LoadedTerm(
        "es.alivio",
        ("alivio", "alivios", "aliviar", "respiro"),
        "es",
        LoadedTermCategory.CELEBRATION,
        0.45,
        1,
        "state the amount and who receives it",
    ),
    LoadedTerm(
        "es.blindar",
        ("blindar", "blinda", "blindaje", "proteger a toda costa"),
        "es",
        LoadedTermCategory.COMBAT_METAPHOR,
        0.55,
        1,
        "state the legal protection created",
    ),
    LoadedTerm(
        "es.contundente",
        ("contundente", "contundentes", "rotundo", "rotunda", "abrumador", "abrumadora"),
        "es",
        LoadedTermCategory.INTENSIFIER,
        0.55,
        1,
        "state the margin or the figure",
    ),
    # -- English, unfavourable ------------------------------------------------
    LoadedTerm(
        "en.disastrous",
        ("disastrous", "disaster", "catastrophic", "catastrophe", "calamitous"),
        "en",
        LoadedTermCategory.CATASTROPHE,
        0.95,
        -1,
        "state the projected outcome and its source",
    ),
    LoadedTerm(
        "en.raid",
        ("raid", "raids", "grab", "cash grab", "plunder", "looting", "loot"),
        "en",
        LoadedTermCategory.MORAL_CHARGE,
        1.0,
        -1,
        "name the transfer and who bears it",
    ),
    LoadedTerm(
        "en.squander",
        ("squander", "squandered", "squandering", "waste of public money", "profligate"),
        "en",
        LoadedTermCategory.MORAL_CHARGE,
        0.8,
        -1,
        "state the spending figure and what it funds",
    ),
    LoadedTerm(
        "en.assault",
        ("assault", "attack", "attacks", "onslaught", "war on", "crackdown"),
        "en",
        LoadedTermCategory.COMBAT_METAPHOR,
        0.7,
        -1,
        "describe the measure and the objection to it",
    ),
    LoadedTerm(
        "en.draconian",
        ("draconian", "punitive", "swingeing", "crippling"),
        "en",
        LoadedTermCategory.INTENSIFIER,
        0.8,
        -1,
        "state the level of the requirement or penalty",
    ),
    LoadedTerm(
        "en.savage",
        ("savage", "savagely", "eye-watering"),
        "en",
        LoadedTermCategory.INTENSIFIER,
        0.8,
        -1,
        "state the size of the change",
    ),
    LoadedTerm(
        "en.scandalous",
        ("scandalous", "outrageous", "shameful", "disgraceful"),
        "en",
        LoadedTermCategory.MORAL_CHARGE,
        0.85,
        -1,
        "state the fact and who disputes it",
    ),
    LoadedTerm(
        "en.reckless",
        ("reckless", "recklessly", "slapdash", "half-baked", "botched"),
        "en",
        LoadedTermCategory.DELEGITIMISING,
        0.7,
        -1,
        "describe the drafting timeline and what was consulted",
    ),
    LoadedTerm(
        "en.populist",
        ("populist", "populism", "demagogic", "demagoguery"),
        "en",
        LoadedTermCategory.IDEOLOGICAL_EPITHET,
        0.75,
        -1,
        "describe the measure and the objection to it",
    ),
    LoadedTerm(
        "en.extremist",
        ("extremist", "dogmatic", "ideological"),
        "en",
        LoadedTermCategory.IDEOLOGICAL_EPITHET,
        0.6,
        -1,
        "state how far the change departs from current rules",
    ),
    LoadedTerm(
        "en.spiral",
        ("spiral", "spiralling", "spiraling", "meltdown", "collapse", "freefall"),
        "en",
        LoadedTermCategory.ALARM,
        0.7,
        -1,
        "state the indicator and the rate of change",
    ),
    LoadedTerm(
        "en.threat",
        ("threat", "threatens", "threatening", "menace", "peril"),
        "en",
        LoadedTermCategory.ALARM,
        0.6,
        -1,
        "state the risk, its probability and its source",
    ),
    LoadedTerm(
        "en.hammer",
        ("hammer", "hammered", "clobber", "clobbered", "slash", "slashed", "axe", "axed"),
        "en",
        LoadedTermCategory.COMBAT_METAPHOR,
        0.65,
        -1,
        "state the size of the reduction",
    ),
    # -- English, favourable --------------------------------------------------
    LoadedTerm(
        "en.historic",
        ("historic", "unprecedented", "landmark", "watershed"),
        "en",
        LoadedTermCategory.CELEBRATION,
        0.7,
        1,
        "state what makes it larger or earlier than prior measures",
    ),
    LoadedTerm(
        "en.miraculous",
        ("miraculous", "miracle", "transformative", "game-changing", "game changer"),
        "en",
        LoadedTermCategory.CELEBRATION,
        0.85,
        1,
        "state the projected effect and its source",
    ),
    LoadedTerm(
        "en.bold",
        ("bold", "brave", "courageous", "ambitious"),
        "en",
        LoadedTermCategory.CELEBRATION,
        0.55,
        1,
        "state the scale of the change",
    ),
    LoadedTerm(
        "en.giveaway",
        ("giveaway", "handout", "handouts", "largesse", "bonanza"),
        "en",
        LoadedTermCategory.MORAL_CHARGE,
        0.8,
        -1,
        "name the transfer, its size and its recipients",
    ),
    LoadedTerm(
        "en.relief",
        ("much-needed", "much needed", "long-overdue", "long overdue", "welcome relief"),
        "en",
        LoadedTermCategory.CELEBRATION,
        0.5,
        1,
        "state the amount and who receives it",
    ),
    LoadedTerm(
        "en.decisive",
        ("decisive", "resounding", "overwhelming", "sweeping"),
        "en",
        LoadedTermCategory.INTENSIFIER,
        0.55,
        1,
        "state the margin or the figure",
    ),
)


def _validate_lexicon(lexicon: Sequence[LoadedTerm]) -> None:
    """Enforce the lexicon's invariants at import time.

    The checks are cheap and they are the mechanism, not a formality. A form
    containing an uppercase letter is the shape a proper noun arrives in, and
    proper nouns are exactly what must never enter this table: a lexicon that
    matched an actor's name would score an article for whom it wrote about. The
    remaining checks stop a duplicated or unbounded entry from silently
    double-counting a sentence.
    """
    seen_ids: set[str] = set()
    seen_forms: set[str] = set()
    for term in lexicon:
        if term.id in seen_ids:
            raise ValueError(f"duplicate lexicon id {term.id!r}")
        seen_ids.add(term.id)
        if not 0.0 < term.intensity <= 1.0:
            raise ValueError(f"{term.id}: intensity must be in (0,1], got {term.intensity}")
        if term.valence not in (-1, 1):
            raise ValueError(f"{term.id}: valence must be -1 or +1, got {term.valence}")
        if not term.neutral_alternative.strip():
            raise ValueError(
                f"{term.id}: a term may only be called loaded if a neutral wording "
                "of the same fact exists; name it"
            )
        if not term.forms:
            raise ValueError(f"{term.id}: no surface forms")
        for form in term.forms:
            if form != fold(form):
                raise ValueError(
                    f"{term.id}: form {form!r} is not folded-lowercase. Capitalised "
                    "entries are how proper nouns arrive, and the loaded-language "
                    "lexicon must contain no actor, party or institution name."
                )
            if form in seen_forms:
                raise ValueError(f"{term.id}: form {form!r} already claimed by another entry")
            seen_forms.add(form)


_validate_lexicon(LOADED_LANGUAGE_LEXICON)


def _form_pattern(form: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(form)}(?![a-z0-9])")


_LEXICON_PATTERNS: Final[tuple[tuple[LoadedTerm, str, re.Pattern[str]], ...]] = tuple(
    (term, form, _form_pattern(form))
    for term in LOADED_LANGUAGE_LEXICON
    # Longest form first so "waste of public money" wins over a bare substring.
    for form in sorted(term.forms, key=len, reverse=True)
)


# ---------------------------------------------------------------------------
# Modality, causality, attribution and evaluation cues
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ModalityCue:
    """A phrase that fixes how certain a statement is presented as being.

    ``certainty`` is a position on a single documented ladder from 0 (explicitly
    unknown) to 1 (asserted as settled), shared by article text and evidence
    text so the two are directly comparable. That comparability is the whole
    mechanism of ``certainty_inflation``.
    """

    id: str
    forms: tuple[str, ...]
    certainty: float
    label: str


#: The certainty ladder. Both an article sentence and an evidence statement are
#: placed on it by the same function, so "the evidence estimates, the article
#: asserts" becomes an arithmetic difference rather than an impression.
MODALITY_CUES: Final[tuple[ModalityCue, ...]] = (
    ModalityCue(
        "unknown",
        (
            "no se sabe",
            "se desconoce",
            "es incierto",
            "incierta",
            "uncertain",
            "unknown",
            "unclear",
        ),
        0.15,
        "explicitly unknown",
    ),
    ModalityCue(
        "estimate",
        (
            "estima",
            "estiman",
            "estimado",
            "estimacion",
            "estimaciones",
            "proyecta",
            "proyeccion",
            "proyecciones",
            "calcula que",
            "aproximadamente",
            "en torno a",
            "cerca de",
            "unos",
            "hasta",
            "preliminar",
            "estimate",
            "estimates",
            "estimated",
            "projects",
            "projection",
            "projected",
            "approximately",
            "around",
            "up to",
            "roughly",
            "preliminary",
            "on current forecasts",
        ),
        0.35,
        "presented as an estimate",
    ),
    ModalityCue(
        "conditional",
        (
            "podria",
            "podrian",
            "puede que",
            "si se aprueba",
            "en caso de",
            "de aprobarse",
            "could",
            "might",
            "may",
            "would",
            "if approved",
            "if enacted",
            "should the",
        ),
        0.45,
        "conditional",
    ),
    ModalityCue(
        "expectation",
        (
            "se espera",
            "se preve",
            "preve",
            "apunta a",
            "deberia",
            "is expected to",
            "is set to",
            "is forecast to",
            "is likely to",
            "should",
        ),
        0.6,
        "expectation",
    ),
    ModalityCue(
        "assertion_future",
        (
            "sera",
            "seran",
            "generara",
            "generaran",
            "producira",
            "recaudara",
            "reducira",
            "aumentara",
            "permitira",
            "eliminara",
            "va a",
            "van a",
            "will",
            "will be",
            "is going to",
            "guarantees",
            "garantiza",
            "asegura que",
        ),
        0.95,
        "asserted as certain",
    ),
)

#: Certainty assumed for a bare declarative that carries a figure but no cue.
#: A flat declarative asserts; that is what makes it a declarative.
BARE_ASSERTION_CERTAINTY: Final[float] = 0.85

_MODALITY_PATTERNS: Final[tuple[tuple[ModalityCue, str, re.Pattern[str]], ...]] = tuple(
    (cue, form, _form_pattern(form))
    for cue in MODALITY_CUES
    for form in sorted(cue.forms, key=len, reverse=True)
)


@dataclass(frozen=True, slots=True)
class CausalCue:
    """A connective that asserts one thing produced another.

    ``cause_side`` records which clause holds the cause, so the two halves can be
    matched separately against the evidence: a causal claim is backed only when
    something in the record links *these two specific things*, not when it merely
    mentions one of them.

    ``hedged`` marks connectives that already concede uncertainty
    ("may have contributed"). These are not scored as unsupported assertions;
    they are scored at a fraction, because hedging is the correct behaviour when
    the warrant is thin.
    """

    id: str
    forms: tuple[str, ...]
    cause_side: str
    """``'before'`` or ``'after'`` the connective."""
    hedged: bool = False


CAUSAL_CUES: Final[tuple[CausalCue, ...]] = (
    CausalCue("es.porque", ("porque", "ya que", "puesto que", "dado que"), "after"),
    CausalCue("es.debido", ("debido a", "a causa de", "por culpa de", "producto de"), "after"),
    CausalCue("es.gracias", ("gracias a",), "after"),
    CausalCue(
        "es.provoco",
        ("provoco", "provoca", "provocara", "genero", "genera", "generara", "causo", "causa"),
        "before",
    ),
    CausalCue(
        "es.desencadeno",
        ("desencadeno", "desato", "detono", "se traduce en", "se tradujo en", "derivo en"),
        "before",
    ),
    CausalCue(
        "es.consecuencia",
        ("como consecuencia de", "a raiz de", "fruto de", "por efecto de"),
        "after",
    ),
    CausalCue(
        "es.contribuyo",
        ("habria contribuido", "podria haber contribuido", "contribuiria a"),
        "before",
        hedged=True,
    ),
    CausalCue("en.because", ("because", "since", "as a result of", "owing to"), "after"),
    CausalCue("en.due", ("due to", "thanks to", "on account of", "driven by"), "after"),
    CausalCue(
        "en.caused",
        ("caused", "causes", "led to", "resulted in", "triggered", "sparked", "drove"),
        "before",
    ),
    CausalCue(
        "en.contributed",
        ("may have contributed", "could have contributed", "is thought to have"),
        "before",
        hedged=True,
    ),
)

#: Phrases that assert co-occurrence rather than production. Present so the
#: analyser does not score correct, careful wording as a causal overreach.
CORRELATION_CUES: Final[tuple[str, ...]] = (
    "coincide con",
    "coincidio con",
    "se asocia con",
    "en paralelo a",
    "al mismo tiempo que",
    "coincides with",
    "coincided with",
    "is associated with",
    "correlates with",
    "alongside",
)

#: Cues that hand a statement to somebody else. Their presence is what separates
#: "the measure is inadequate" from "the association called the measure
#: inadequate" — the first is the outlet asserting, the second is reporting.
ATTRIBUTION_CUES: Final[tuple[str, ...]] = (
    "segun",
    "de acuerdo con",
    "conforme a",
    "afirmo",
    "afirma",
    "afirman",
    "sostuvo",
    "sostiene",
    "dijo",
    "dice",
    "declaro",
    "senalo",
    "advirtio",
    "advierte",
    "critico",
    "cuestiono",
    "estimo que",
    "planteo",
    "argumento",
    "a juicio de",
    "para el organismo",
    "el informe indica",
    "el documento senala",
    "according to",
    "said",
    "says",
    "stated",
    "argued",
    "argues",
    "warned",
    "warns",
    "criticised",
    "criticized",
    "claimed",
    "claims",
    "told",
    "in the view of",
    "the report says",
    "the document states",
)

#: First-person and explicit-stance markers. A sentence carrying one is signalling
#: opinion to the reader, which is the opposite of dressing opinion as fact.
STANCE_MARKERS: Final[tuple[str, ...]] = (
    "a mi juicio",
    "en mi opinion",
    "creo que",
    "considero que",
    "me parece",
    "sostengo que",
    "esta columna",
    "in my view",
    "i think",
    "i believe",
    "we believe",
    "in our view",
    "this column",
    "arguably",
)

#: Evaluative and normative predicates: wording that grades or prescribes rather
#: than describes. Deliberately about *quality and obligation*, not about
#: subject matter, so the same list applies to any document in any jurisdiction.
EVALUATIVE_PREDICATES: Final[tuple[str, ...]] = (
    "es insuficiente",
    "es inaceptable",
    "es injusto",
    "es injusta",
    "es absurdo",
    "es absurda",
    "es un error",
    "es un acierto",
    "es necesario",
    "es imprescindible",
    "es urgente",
    "resulta insuficiente",
    "resulta evidente",
    "no tiene sentido",
    "carece de sentido",
    "deja mucho que desear",
    "debe",
    "deben",
    "deberia",
    "hay que",
    "tendria que",
    "lo correcto es",
    "lo razonable es",
    "is inadequate",
    "is unacceptable",
    "is unfair",
    "is unjust",
    "is absurd",
    "is a mistake",
    "is the right",
    "is necessary",
    "is essential",
    "is urgent",
    "makes no sense",
    "falls far short",
    "must",
    "should",
    "ought to",
    "needs to",
    "the right thing",
    "the sensible thing",
)

_CORRELATION_PATTERNS = tuple(_form_pattern(f) for f in CORRELATION_CUES)
_ATTRIBUTION_PATTERNS = tuple((f, _form_pattern(f)) for f in ATTRIBUTION_CUES)
_STANCE_PATTERNS = tuple((f, _form_pattern(f)) for f in STANCE_MARKERS)
_EVALUATIVE_PATTERNS = tuple(
    (f, _form_pattern(f)) for f in sorted(EVALUATIVE_PREDICATES, key=len, reverse=True)
)
_CAUSAL_PATTERNS: Final[tuple[tuple[CausalCue, str, re.Pattern[str]], ...]] = tuple(
    (cue, form, _form_pattern(form))
    for cue in CAUSAL_CUES
    for form in sorted(cue.forms, key=len, reverse=True)
)


def certainty_of(folded_text: str, *, default: float) -> tuple[float, tuple[str, ...]]:
    """Place a passage on the shared certainty ladder.

    Returns the strongest certainty asserted anywhere in the passage together
    with the cues that produced it. The *maximum* is taken deliberately: a
    sentence that says "the agency estimates X, so revenue will rise by Y" has
    asserted Y as settled, and averaging the hedge into it would hide exactly the
    move ``certainty_inflation`` is looking for.
    """
    found: list[str] = []
    levels: list[float] = []
    for cue, form, pattern in _MODALITY_PATTERNS:
        if pattern.search(folded_text):
            found.append(f"{form} ({cue.label})")
            levels.append(cue.certainty)
    if not levels:
        return default, ()
    return max(levels), tuple(sorted(set(found)))


# ---------------------------------------------------------------------------
# Scoring primitives
# ---------------------------------------------------------------------------


def saturate(rate: float, *, half: float) -> float:
    """Map an unbounded rate into ``[0,1)`` with a documented half-way point.

    ``saturate(half, half=half) == 0.5``. Used instead of a hard cap so that a
    very high rate is distinguishable from a merely high one, and so that no
    threshold has to be defended as the point where a property "starts".
    """
    if rate <= 0:
        return 0.0
    return 1.0 - math.pow(2.0, -rate / half)


def to_score(value: float) -> int:
    """Clamp a ``[0,1]`` value onto the contract's 0-100 integer scale."""
    return max(0, min(100, int(round(value * 100))))


def apportion(score: int, weights: Sequence[float]) -> list[float]:
    """Split ``score`` points across contributors so the parts sum to the whole.

    Components are the finding and the score is their summary, so the summary has
    to be recoverable by addition. Residual rounding error is assigned to the
    largest contributor, which is the only placement that cannot change which
    component a reader thinks dominated.
    """
    total = sum(w for w in weights if w > 0)
    if total <= 0 or not weights:
        return [0.0 for _ in weights]
    points = [round(score * max(w, 0.0) / total, 3) for w in weights]
    residual = round(score - sum(points), 3)
    if residual and points:
        biggest = max(range(len(points)), key=lambda i: points[i])
        points[biggest] = round(points[biggest] + residual, 3)
    return points


def _confidence(
    value: float,
    *,
    basis: Sequence[ConfidenceBasis] = (),
    limiting_factor: str | None = None,
) -> Confidence:
    return Confidence(
        evidence_confidence=max(0.0, min(1.0, round(value, 3))),
        basis=list(basis),
        limiting_factor=limiting_factor,
    )


def _basis(factor: ConfidenceFactor, effect: ConfidenceEffect, note: str) -> ConfidenceBasis:
    return ConfidenceBasis(factor=factor, effect=effect, note=note)


def _direction_of(weight: float) -> Direction:
    if weight > 0:
        return Direction.POSITIVE
    if weight < 0:
        return Direction.NEGATIVE
    return Direction.NONE


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Calculation:
    """The arithmetic that turned observations into a score.

    Published verbatim so that disagreement can be about a specific step. A
    reader who thinks the half-way point is wrong can say so; a reader shown only
    the output can only say the output feels wrong.
    """

    formula: str
    inputs: Mapping[str, float | int | str]
    steps: tuple[str, ...]
    raw_value: float
    score: int


@dataclass(frozen=True, slots=True)
class DimensionResult:
    """One framing dimension, and the complete record behind it.

    This is what :meth:`FramingAnalysis.explain` returns. It contains no
    judgement, no severity band and no colour: the score, the passages, the
    counts, the formula, what could not be resolved, and what points the other
    way. Interpretation belongs to the reader, and the polarity field tells an
    interface which end of the scale is which.
    """

    key: FramingDimensionKey
    score: int
    polarity: Polarity
    components: tuple[Component, ...]
    evidence_refs: tuple[str, ...]
    confidence: Confidence
    rationale: str
    sentences: tuple[SentenceRef, ...]
    """Exactly the sentences that entered the calculation, in article order."""
    calculation: Calculation
    uncertainties: tuple[Uncertainty, ...]
    counter_evidence: tuple[str, ...]
    """Observations pointing away from the score — hedges the article did use,
    sources it did cite, charged terms it confined to quotations. Published so a
    score is never the only thing a reader sees."""

    def to_model(self) -> FramingDimension:
        """Render as the contract model, with polarity pinned by dimension."""
        cls: type[FramingDimension]
        cls = (
            FramingDimensionHigherIsBetter
            if self.polarity is Polarity.HIGHER_IS_BETTER
            else FramingDimensionLowerIsBetter
        )
        return cls(
            score=self.score,
            components=list(self.components),
            evidence_refs=list(self.evidence_refs),
            confidence=self.confidence,
            rationale=self.rationale,
        )


#: Which of the eight are merits and which are faults. Pinned here as well as in
#: the models so a dimension can never be constructed with the wrong polarity.
DIMENSION_POLARITY: Final[Mapping[FramingDimensionKey, Polarity]] = {
    FramingDimensionKey.SELECTION_ASYMMETRY: Polarity.LOWER_IS_BETTER,
    FramingDimensionKey.LOADED_LANGUAGE: Polarity.LOWER_IS_BETTER,
    FramingDimensionKey.CONTEXT_OMISSION: Polarity.LOWER_IS_BETTER,
    FramingDimensionKey.CERTAINTY_INFLATION: Polarity.LOWER_IS_BETTER,
    FramingDimensionKey.UNSUPPORTED_CAUSAL_LANGUAGE: Polarity.LOWER_IS_BETTER,
    FramingDimensionKey.OPINION_AS_FACT: Polarity.LOWER_IS_BETTER,
    FramingDimensionKey.SOURCE_DIVERSITY: Polarity.HIGHER_IS_BETTER,
    FramingDimensionKey.PRIMARY_SOURCE_GROUNDING: Polarity.HIGHER_IS_BETTER,
}


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArticleUnderAnalysis:
    """An article plus the text actually available for it.

    ``body_text`` is separate from :class:`NewsArticle` because the contract
    model carries an article's *extraction*, not its bytes. When it is ``None``
    the analysis runs on the headline and standfirst alone, which is a much
    weaker analysis — and every dimension records that as a limitation rather
    than reporting a confident score over four visible words.
    """

    article: NewsArticle
    body_text: str | None = None

    def zones(self) -> tuple[SentenceRef, ...]:
        """Return every sentence of the article, tagged by zone, in reading order."""
        refs: list[SentenceRef] = []
        refs.extend(_sentences_from(self.article.headline, Zone.HEADLINE, 0, 0))
        if self.article.dek:
            refs.extend(_sentences_from(self.article.dek, Zone.DEK, 0, len(refs)))
        if self.body_text:
            refs.extend(_sentences_from(self.body_text, Zone.BODY, 0, len(refs)))
        return tuple(refs)

    @property
    def has_body(self) -> bool:
        """Whether the article's own text — not merely its metadata — was available."""
        return bool(self.body_text and self.body_text.strip()) and self.article.body_available


@dataclass(frozen=True, slots=True)
class FramingContext:
    """Everything the eight dimensions measure an article *against*.

    An article is never scored against an imagined ideal. It is scored against
    the propositions the primary document contains, the evidence that was
    actually collected, the claims extracted from it, and the rest of the
    cluster — because "this was omitted" is only a finding if the material
    existed and other coverage found it worth reporting.
    """

    propositions: tuple[Proposition, ...] = ()
    provisions: tuple[Provision, ...] = ()
    monetary_values: tuple[MonetaryValue, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    claims: tuple[Claim, ...] = ()
    peers: tuple[ArticleUnderAnalysis, ...] = ()
    """The other articles in the same cluster. Their coverage is the baseline for
    ``context_omission`` and part of the baseline for ``selection_asymmetry``."""
    cluster: NewsCluster | None = None
    independence: IndependenceAnalysis | None = None
    document_id: str | None = None

    def evidence_by_id(self) -> Mapping[str, EvidenceItem]:
        return {item.id: item for item in self.evidence}

    def claims_for(self, article_id: str) -> tuple[Claim, ...]:
        return tuple(claim for claim in self.claims if claim.article_id == article_id)


# ---------------------------------------------------------------------------
# Independence: delegated to aleph.news.independence when it is available
# ---------------------------------------------------------------------------

#: Entry points tried, in order, on :mod:`aleph.news.independence`. That module
#: owns the canonical syndication analysis; this module only *consumes* an
#: :class:`IndependenceAnalysis`, and must never invent one.
INDEPENDENCE_ENTRYPOINTS: Final[tuple[str, ...]] = (
    "analyse_independence",
    "analyze_independence",
    "compute_independence",
    "independence_analysis",
)


def resolve_independence(context: FramingContext) -> IndependenceAnalysis | None:
    """Return the independence analysis governing this article's cluster.

    Resolution order, most authoritative first:

    1. an analysis passed in explicitly;
    2. the one carried by the cluster — ``NewsCluster.independence_analysis`` is
       a required field precisely so this is always available in a real bundle;
    3. :mod:`aleph.news.independence`, if it exposes one of
       :data:`INDEPENDENCE_ENTRYPOINTS`.

    Returning ``None`` is a legitimate outcome and is handled honestly
    downstream: ``source_diversity`` then counts cited sources *without*
    collapsing syndicated duplicates, reports that it could not collapse them,
    and lowers its own confidence. It never assumes independence it has not
    checked, because assuming it is how forty copies of one wire story become
    forty sources.
    """
    if context.independence is not None:
        return context.independence
    if context.cluster is not None:
        return context.cluster.independence_analysis
    try:  # pragma: no cover - exercised only when the news package is present
        import aleph.news.independence as independence_module
    except ImportError:
        return None
    articles = [subject.article for subject in context.peers]
    for name in INDEPENDENCE_ENTRYPOINTS:
        fn = getattr(independence_module, name, None)
        if callable(fn) and articles:
            result = fn(articles)
            if isinstance(result, IndependenceAnalysis):
                return result
    return None


def _origin_map(analysis: IndependenceAnalysis | None) -> Mapping[str, str]:
    """Map every derivative item id onto the id of the original it reproduces.

    This is what collapses apparent corroboration back to what was actually
    observed. Both traced chains and shared-origin signals feed it; for a signal
    group with no identified origin the lexicographically smallest id is used as
    an arbitrary but stable representative, which is enough to stop the group
    from being counted more than once.
    """
    if analysis is None:
        return {}
    mapping: dict[str, str] = {}
    for chain in analysis.syndication_chains:
        for downstream in chain.downstream_article_ids:
            mapping[downstream] = chain.origin_article_id
    for signal in analysis.shared_origin_evidence:
        representative = min(signal.article_ids)
        for member in signal.article_ids:
            mapping.setdefault(member, representative)
    # Follow chains to their root so a two-hop reproduction collapses fully.
    resolved: dict[str, str] = {}
    for key in mapping:
        seen = {key}
        cursor = key
        while cursor in mapping and mapping[cursor] not in seen:
            cursor = mapping[cursor]
            seen.add(cursor)
        resolved[key] = cursor
    return resolved


# ---------------------------------------------------------------------------
# Dimension 1: loaded_language
# ---------------------------------------------------------------------------

#: Multiplier applied to a charged term found inside quotation marks. Quoting a
#: speaker's word is reporting; choosing it in the outlet's own voice is
#: framing. The value is not zero because *which* quotes are selected is itself
#: an editorial act.
QUOTED_TERM_DISCOUNT: Final[float] = 0.35

#: Occurrences of one term counted at full weight before diminishing returns.
#: A word repeated eleven times says roughly what it said the third time.
MAX_FULL_WEIGHT_OCCURRENCES: Final[int] = 3

#: Weighted loaded terms per 100 words at which the score reaches 50.
LOADED_LANGUAGE_HALF_RATE: Final[float] = 3.0


def score_loaded_language(
    subject: ArticleUnderAnalysis, sentences: Sequence[SentenceRef]
) -> DimensionResult:
    """Measure evaluative wording where a neutral description was available.

    Matches :data:`LOADED_LANGUAGE_LEXICON` against the article's folded text and
    weights each hit by three things a reader can check: the term's intensity,
    the exposure of the zone it appeared in, and whether it sat inside a
    quotation. The result is normalised per 100 words, so a long article is not
    penalised for being long and a charged headline over a short piece is not
    diluted into invisibility.

    The lexicon names no actor, so this dimension cannot respond to *whom* an
    article is about. It also scores favourable and unfavourable charge
    identically: an article that calls a measure "miraculous" is doing the same
    thing as one that calls it "a raid".
    """
    word_count = sum(len(_TOKEN.findall(s.folded)) for s in sentences) or 1
    hits: dict[str, list[tuple[SentenceRef, str, float]]] = {}
    involved: list[SentenceRef] = []
    quoted_hits = 0

    for sentence in sentences:
        if sentence.weight <= 0:
            continue
        consumed: list[tuple[int, int]] = []
        for term, form, pattern in _LEXICON_PATTERNS:
            for match in pattern.finditer(sentence.folded):
                if any(a <= match.start() < b for a, b in consumed):
                    continue
                consumed.append((match.start(), match.end()))
                weight = term.intensity * sentence.weight
                if sentence.in_quotation:
                    weight *= QUOTED_TERM_DISCOUNT
                    quoted_hits += 1
                hits.setdefault(term.id, []).append((sentence, form, weight))
                if sentence not in involved:
                    involved.append(sentence)

    lexicon_by_id = {term.id: term for term in LOADED_LANGUAGE_LEXICON}
    weighted_total = 0.0
    per_term: list[tuple[LoadedTerm, float, list[tuple[SentenceRef, str]]]] = []
    for term_id in sorted(hits):
        occurrences = hits[term_id]
        term = lexicon_by_id[term_id]
        subtotal = 0.0
        for rank, (_, _, weight) in enumerate(occurrences):
            # Diminishing returns after the third occurrence of the same term.
            subtotal += weight if rank < MAX_FULL_WEIGHT_OCCURRENCES else weight * 0.4
        weighted_total += subtotal
        per_term.append((term, subtotal, [(s, f) for s, f, _ in occurrences]))

    rate = weighted_total / word_count * 100.0
    raw = saturate(rate, half=LOADED_LANGUAGE_HALF_RATE)
    score = to_score(raw)

    per_term.sort(key=lambda entry: (-entry[1], entry[0].id))
    points = apportion(score, [subtotal for _, subtotal, _ in per_term])
    components = [
        Component(
            label=f"{term.forms[0]!r} ({term.category.value}, intensity {term.intensity:g})",
            direction=_direction_of(point),
            weight=point,
            note=(
                f"{len(occ)} occurrence(s); "
                + "; ".join(
                    f"{'quoted' if s.in_quotation else s.zone.value}: “{s.text}”"
                    for s, _ in occ[:3]
                )
                + f". Neutral alternative available: {term.neutral_alternative}."
            ),
        )
        for (term, _, occ), point in zip(per_term, points, strict=True)
    ]

    counter: list[str] = []
    unloaded = len([s for s in sentences if s.weight > 0]) - len(involved)
    if unloaded > 0:
        counter.append(f"{unloaded} of {len(sentences)} sentences contain no lexicon term")
    if quoted_hits:
        counter.append(
            f"{quoted_hits} charged term(s) appear inside quotation marks and were "
            f"discounted to {QUOTED_TERM_DISCOUNT:g} of full weight, since quoting a "
            "speaker's word is not the same editorial act as choosing it"
        )
    if not per_term:
        counter.append("no term in the lexicon matched this article")

    uncertainties: list[Uncertainty] = []
    if not subject.has_body:
        uncertainties.append(
            Uncertainty(
                statement=(
                    "Only the headline and standfirst were available, so the body's "
                    "wording is unmeasured."
                ),
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by="retrieving the article body",
            )
        )
    if subject.article.language and not subject.article.language.lower().startswith(("es", "en")):
        uncertainties.append(
            Uncertainty(
                statement=(
                    f"The lexicon covers Spanish and English; this article is tagged "
                    f"{subject.article.language!r}, so charged wording may be missed."
                ),
                kind=UncertaintyKind.MEASUREMENT,
                resolvable_by="extending the lexicon to this language",
            )
        )

    confidence = _confidence(
        0.8 if subject.has_body else 0.35,
        basis=[
            _basis(
                ConfidenceFactor.RETRIEVAL_COMPLETENESS,
                ConfidenceEffect.RAISES if subject.has_body else ConfidenceEffect.LOWERS,
                "full body text available" if subject.has_body else "headline and standfirst only",
            ),
            _basis(
                ConfidenceFactor.CLAIM_AMBIGUITY,
                ConfidenceEffect.LOWERS,
                "lexicon matching cannot detect charge carried by sentence structure, "
                "juxtaposition or ordering alone",
            ),
        ],
        limiting_factor=(
            None if subject.has_body else "no body text: only the headline could be examined"
        ),
    )

    return DimensionResult(
        key=FramingDimensionKey.LOADED_LANGUAGE,
        score=score,
        polarity=Polarity.LOWER_IS_BETTER,
        components=tuple(components),
        evidence_refs=(),
        confidence=confidence,
        rationale=(
            f"{len(per_term)} distinct evaluative term(s) matched over {word_count} words "
            f"({rate:.2f} intensity-weighted matches per 100 words). Each match names a "
            "neutral wording of the same fact that was available."
        ),
        sentences=tuple(involved),
        calculation=Calculation(
            formula="score = 100 · (1 − 2^(−rate/half)), rate = Σ(intensity · zone · quote_discount) / words · 100",
            inputs={
                "words": word_count,
                "distinct_terms": len(per_term),
                "weighted_matches": round(weighted_total, 3),
                "rate_per_100_words": round(rate, 3),
                "half": LOADED_LANGUAGE_HALF_RATE,
            },
            steps=(
                f"summed intensity × zone weight over {sum(len(o) for _, _, o in per_term)} matches = {weighted_total:.3f}",
                f"normalised over {word_count} words → {rate:.3f} per 100 words",
                f"saturating at half-rate {LOADED_LANGUAGE_HALF_RATE:g} → {raw:.3f}",
            ),
            raw_value=round(raw, 4),
            score=score,
        ),
        uncertainties=tuple(uncertainties),
        counter_evidence=tuple(counter),
    )


# ---------------------------------------------------------------------------
# Dimension 2: certainty_inflation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceStatement:
    """One statement from the record, placed on the shared certainty ladder.

    ``why`` records how the certainty was derived — a modal cue in the text, a
    proposition's declared modality, or the document's own ``is_estimate`` flag —
    so a reader disputing an inflation finding can dispute the specific reading
    of the source rather than the finding as a whole.
    """

    ref: str
    text: str
    certainty: float
    cues: tuple[str, ...]
    terms: frozenset[str]
    numbers: frozenset[str]
    why: str


#: Certainty implied by a source's own form when it states no modal cue. A
#: figure the document flags as an estimate is an estimate whether or not the
#: sentence around it says so.
_TIER_DEFAULT_CERTAINTY: Final[Mapping[EvidenceTier, float]] = {
    EvidenceTier.PRIMARY_DOCUMENT: 0.9,
    EvidenceTier.LEGISLATIVE_RECORD: 0.9,
    EvidenceTier.STATISTICAL_DATASET: 0.85,
    EvidenceTier.OFFICIAL_TECHNICAL_REPORT: 0.6,
    EvidenceTier.PEER_REVIEWED: 0.6,
    EvidenceTier.EXPERT_ANALYSIS: 0.5,
    EvidenceTier.JOURNALISM: 0.6,
    EvidenceTier.POLITICAL_STATEMENT: 0.5,
    EvidenceTier.SOCIAL_MEDIA: 0.4,
}

#: Modalities that mark a proposition as something other than settled fact.
_MODALITY_CERTAINTY: Final[Mapping[Modality, float]] = {
    Modality.ASSERTED: 0.9,
    Modality.OBLIGATORY: 0.9,
    Modality.PROHIBITIVE: 0.9,
    Modality.PERMISSIVE: 0.6,
    Modality.CONDITIONAL: 0.45,
    Modality.HYPOTHETICAL: 0.35,
    Modality.REPORTED: 0.6,
    Modality.PROPOSED: 0.5,
}


def build_source_statements(context: FramingContext) -> tuple[SourceStatement, ...]:
    """Place every statement in the record on the same certainty ladder.

    Evidence items, propositions and the document's own monetary figures all
    contribute. The point is comparability: once a source and an article
    sentence are on one ladder, "the evidence estimates, the article asserts" is
    a subtraction rather than an impression, and the difference is quotable in
    both directions.
    """
    out: list[SourceStatement] = []

    for item in context.evidence:
        folded = fold(item.statement)
        default = _TIER_DEFAULT_CERTAINTY.get(item.tier, 0.6)
        certainty, cues = certainty_of(folded, default=default)
        out.append(
            SourceStatement(
                ref=item.id,
                text=item.statement,
                certainty=certainty,
                cues=cues,
                terms=content_terms(folded),
                numbers=numeric_tokens(item.statement) | _quantity_numbers(item),
                why=(
                    f"evidence item, tier {item.tier.value}"
                    + (f", cues: {', '.join(cues)}" if cues else ", no modal cue; tier default")
                ),
            )
        )

    for proposition in context.propositions:
        folded = fold(proposition.text)
        default = _MODALITY_CERTAINTY.get(proposition.modality or Modality.ASSERTED, 0.9)
        if proposition.proposition_type is PropositionType.ASSUMPTION:
            default = min(default, 0.35)
        if proposition.hedges:
            default = min(default, 0.4)
        certainty, cues = certainty_of(folded, default=default)
        out.append(
            SourceStatement(
                ref=proposition.id,
                text=proposition.text,
                certainty=certainty,
                cues=cues,
                terms=content_terms(folded),
                numbers=numeric_tokens(proposition.text),
                why=(
                    f"primary proposition, modality "
                    f"{(proposition.modality or Modality.ASSERTED).value}"
                    + (f", hedges: {', '.join(proposition.hedges)}" if proposition.hedges else "")
                ),
            )
        )

    for value in context.monetary_values:
        certainty = 0.35 if value.is_estimate or value.role is MonetaryRole.PROJECTION else 0.9
        money = value.money
        text = (
            f"{value.label}: {money.amount:g} {money.currency} ({money.unit.value})"
            + (f", {money.year}" if money.year else "")
            + f" — “{value.span.text}”"
        )
        out.append(
            SourceStatement(
                ref=value.provision_id or value.id,
                text=text,
                certainty=certainty,
                cues=("is_estimate",) if value.is_estimate else (),
                terms=content_terms(fold(f"{value.label} {value.span.text}")),
                numbers=numeric_tokens(f"{money.amount:g} {value.span.text}"),
                why=(
                    f"document figure {value.label!r}, role {value.role.value}"
                    + (
                        ", flagged by the document as an estimate"
                        if value.is_estimate
                        else ", stated by the document as settled"
                    )
                ),
            )
        )
    return tuple(out)


def _quantity_numbers(item: EvidenceItem) -> frozenset[str]:
    parts = [str(q.value) for q in item.quantities] + [str(m.amount) for m in item.money]
    return numeric_tokens(" ".join(parts)) if parts else frozenset()


#: Minimum term overlap for an article sentence and a source statement to be
#: treated as being about the same thing when they share no figure.
MATCH_OVERLAP_THRESHOLD: Final[float] = 0.30

#: Integers that are almost certainly calendar years. A shared year is a weak
#: anchor — two statements about the same reform naturally share its start date
#: while describing completely different quantities — so it must not outrank a
#: shared amount.
_YEAR_LIKE = re.compile(r"^(1[89]\d{2}|20\d{2}|21\d{2})$")

#: Strength difference within which two candidate sources count as equally good.
_TIE_MARGIN: Final[float] = 0.05


def _best_source(
    sentence: SentenceRef, sources: Sequence[SourceStatement]
) -> tuple[SourceStatement | None, float, str]:
    """Find the source statement an article sentence is talking about.

    A shared *amount* is the strongest anchor; a shared year is a weak one, since
    coverage of one reform naturally repeats its start date while describing
    quite different quantities. Failing both, topical overlap must clear
    :data:`MATCH_OVERLAP_THRESHOLD`.

    Where several sources match about equally well, the one stated **most
    firmly** is chosen. That is the conservative tie-break: it minimises the
    measured excess, so a finding of certainty inflation can never be an
    artefact of the analyser having picked the most hedged of several plausible
    sources.

    When nothing matches, the sentence is *excluded* from the score and recorded
    as an uncertainty. Not knowing what the source said is not the same as
    knowing the article overstated it.
    """
    scored: list[tuple[float, SourceStatement, str]] = []
    for source in sources:
        shared = sentence.numbers & source.numbers
        strong = {n for n in shared if not _YEAR_LIKE.match(n)}
        term_overlap = overlap(sentence.terms, source.terms)
        if strong:
            strength = 0.65 + 0.35 * term_overlap
            why = f"shares figure(s) {', '.join(sorted(strong))}"
        elif shared:
            strength = 0.35 + 0.45 * term_overlap
            why = f"shares only the year {', '.join(sorted(shared))}"
        elif term_overlap >= MATCH_OVERLAP_THRESHOLD:
            strength = term_overlap
            why = f"topical overlap {term_overlap:.2f}"
        else:
            continue
        scored.append((strength, source, why))

    if not scored:
        return None, 0.0, ""
    best_strength = max(strength for strength, _, _ in scored)
    tied = [row for row in scored if row[0] >= best_strength - _TIE_MARGIN]
    strength, source, why = max(tied, key=lambda row: (row[1].certainty, row[0], row[1].ref))
    return source, strength, why


@dataclass(frozen=True, slots=True)
class _ModalityPair:
    """One article sentence set beside the source statement it restates."""

    sentence: SentenceRef
    source: SourceStatement
    article_certainty: float
    excess: float
    pair_weight: float
    pairing_reason: str
    article_cues: tuple[str, ...]


def score_certainty_inflation(
    subject: ArticleUnderAnalysis,
    sentences: Sequence[SentenceRef],
    sources: Sequence[SourceStatement],
) -> DimensionResult:
    """Compare the article's modality against the modality of its sources.

    This comparison *is* the dimension. For every article sentence that can be
    paired with a statement in the record, both are placed on the shared
    certainty ladder and the excess is measured:

        inflation = max(0, article_certainty − source_certainty)

    The evidence says "estimates" (0.35) and the article says "will" (0.95): the
    excess is 0.60 and the sentence pair is published so a reader can check both
    wordings. The floor at zero is deliberate — an article that hedges *more*
    than its source is behaving correctly and is not credited or penalised here.

    Sentences with no matching source do not score. Not knowing what the source
    said is different from knowing the article overstated it, and the difference
    is recorded as an uncertainty rather than absorbed into the number.
    """
    scored: list[_ModalityPair] = []
    unmatched: list[SentenceRef] = []
    correct_hedges: list[str] = []

    for sentence in sentences:
        if sentence.weight <= 0:
            continue
        if not sentence.numbers and len(sentence.terms) < 3:
            continue
        source, strength, why = _best_source(sentence, sources)
        if source is None:
            if sentence.numbers:
                unmatched.append(sentence)
            continue
        article_default = BARE_ASSERTION_CERTAINTY if sentence.numbers else 0.8
        article_certainty, cues = certainty_of(sentence.folded, default=article_default)
        excess = max(0.0, article_certainty - source.certainty)
        if excess <= 0.0:
            correct_hedges.append(
                f"“{sentence.text}” is stated no more firmly than {source.ref} "
                f"({article_certainty:.2f} vs {source.certainty:.2f})"
            )
            continue
        scored.append(
            _ModalityPair(
                sentence=sentence,
                source=source,
                article_certainty=article_certainty,
                excess=excess,
                pair_weight=sentence.weight * strength,
                pairing_reason=why,
                article_cues=cues,
            )
        )

    total_weight = sum(pair.pair_weight for pair in scored)
    raw = (
        sum(pair.excess * pair.pair_weight for pair in scored) / total_weight
        if total_weight > 0
        else 0.0
    )
    score = to_score(raw)

    scored.sort(key=lambda pair: (-pair.excess * pair.pair_weight, pair.sentence.index))
    points = apportion(score, [pair.excess * pair.pair_weight for pair in scored])
    components = [
        Component(
            label=(
                f"{pair.sentence.zone.value} states at certainty "
                f"{pair.article_certainty:.2f} what {pair.source.ref} states at "
                f"{pair.source.certainty:.2f}"
            ),
            direction=_direction_of(point),
            weight=point,
            evidence_refs=[pair.source.ref] if _is_ref(pair.source.ref) else [],
            note=(
                f"article: “{pair.sentence.text}”"
                + (
                    f" [cues: {', '.join(pair.article_cues)}]"
                    if pair.article_cues
                    else " [no hedge]"
                )
                + f" — source: “{pair.source.text}” ({pair.source.why}); paired because it "
                f"{pair.pairing_reason}; excess certainty {pair.excess:.2f}"
            ),
        )
        for pair, point in zip(scored, points, strict=True)
    ]

    uncertainties: list[Uncertainty] = []
    if unmatched:
        uncertainties.append(
            Uncertainty(
                statement=(
                    f"{len(unmatched)} sentence(s) carrying figures could not be paired with "
                    "any statement in the evidence pool or the primary document, so their "
                    "modality was not compared and they did not enter the score."
                ),
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by="collecting the source of those figures",
            )
        )
    if not sources:
        uncertainties.append(
            Uncertainty(
                statement=(
                    "No evidence items, propositions or document figures were supplied, so "
                    "certainty inflation could not be measured at all."
                ),
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by="running evidence collection before framing analysis",
            )
        )

    coverage = len(scored) + len(unmatched)
    confidence = _confidence(
        0.0 if not sources else min(0.85, 0.3 + 0.11 * len(scored)),
        basis=[
            _basis(
                ConfidenceFactor.PRIMARY_SOURCE_COVERAGE,
                ConfidenceEffect.RAISES if sources else ConfidenceEffect.LOWERS,
                f"{len(sources)} source statement(s) available for comparison",
            ),
            _basis(
                ConfidenceFactor.QUANTITATIVE_VALIDATION,
                ConfidenceEffect.RAISES if scored else ConfidenceEffect.NEUTRAL,
                f"{len(scored)} of {coverage} figure-bearing sentences were matched to a source",
            ),
        ],
        limiting_factor=(
            "no source statements were available to compare against"
            if not sources
            else (
                f"{len(unmatched)} figure-bearing sentence(s) had no matching source"
                if unmatched
                else None
            )
        ),
    )

    return DimensionResult(
        key=FramingDimensionKey.CERTAINTY_INFLATION,
        score=score,
        polarity=Polarity.LOWER_IS_BETTER,
        components=tuple(components),
        evidence_refs=tuple(
            sorted({pair.source.ref for pair in scored if _is_ref(pair.source.ref)})
        ),
        confidence=confidence,
        rationale=(
            f"{len(scored)} of {coverage} matched statement(s) are stated more firmly than the "
            f"source they restate; the mean weighted excess certainty is {raw:.2f} on the "
            "0-1 modality ladder. Sentences that hedge at least as much as their source do "
            "not contribute."
        ),
        sentences=tuple(pair.sentence for pair in scored),
        calculation=Calculation(
            formula="score = 100 · Σ(max(0, article_certainty − source_certainty) · w) / Σw",
            inputs={
                "matched_sentences": len(scored),
                "unmatched_figure_sentences": len(unmatched),
                "source_statements": len(sources),
                "total_pair_weight": round(total_weight, 3),
            },
            steps=(
                f"placed {len(sources)} source statement(s) on the certainty ladder",
                f"paired {len(scored) + len(correct_hedges)} article sentence(s) to a source",
                f"mean weighted excess certainty = {raw:.4f}",
            ),
            raw_value=round(raw, 4),
            score=score,
        ),
        uncertainties=tuple(uncertainties),
        counter_evidence=tuple(correct_hedges[:5]),
    )


def _is_ref(value: str) -> bool:
    """Whether a string is usable as an Aleph id in an ``evidence_refs`` list."""
    return ":" in value and value.split(":", 1)[0] in {
        "doc",
        "prov",
        "prop",
        "clm",
        "ev",
        "art",
        "cluster",
        "contra",
        "actor",
        "node",
        "edge",
        "src",
        "axis",
        "job",
    }


# ---------------------------------------------------------------------------
# Dimension 3: unsupported_causal_language
# ---------------------------------------------------------------------------

#: Weight of a causal claim that is attributed in-sentence to a source but not
#: independently evidenced. Attribution is better practice than bare assertion —
#: the reader knows whose reasoning it is — but attribution is not warrant.
ATTRIBUTED_CAUSAL_WEIGHT: Final[float] = 0.25

#: Weight of a hedged causal claim ("may have contributed"). Hedging is the
#: correct response to a thin warrant, so it is scored low, not zero.
HEDGED_CAUSAL_WEIGHT: Final[float] = 0.35


@dataclass(frozen=True, slots=True)
class _CausalAssertion:
    """One causal claim made by an article, and what was found to back it."""

    sentence: SentenceRef
    cue: CausalCue
    form: str
    weight: float
    """Unsupported weight in ``[0,1]``: 0 when evidence backs the link."""
    status: str
    backing_ref: str | None
    backing_reason: str


def score_unsupported_causal_language(
    sentences: Sequence[SentenceRef], context: FramingContext, article_id: str
) -> DimensionResult:
    """Detect causal connectives whose claim no evidence item backs.

    Each causal sentence is split at its connective into a cause clause and an
    effect clause, and the record is searched for an item that links *those two
    specific things* — an evidence item that is itself causal and shares topical
    terms with both halves, or a claim extracted from this article whose
    evaluation cited evidence. Mentioning one half is not backing: an evidence
    item about the levy does not license "the levy caused the closures".

    Three mitigations are applied, and all three are published:
    correlation wording ("coincides with") is not counted as a causal assertion
    at all; a hedged connective scores at :data:`HEDGED_CAUSAL_WEIGHT`; a claim
    attributed in-sentence scores at :data:`ATTRIBUTED_CAUSAL_WEIGHT`.

    The score is the unsupported share of the article's causal assertions, so an
    article that makes one unsupported causal claim among ten evidenced ones is
    not described the same way as one that makes a single unevidenced claim.
    """
    causal_evidence = [
        item
        for item in context.evidence
        if any(pattern.search(fold(item.statement)) for _, _, pattern in _CAUSAL_PATTERNS)
    ]
    claim_terms: list[tuple[str, frozenset[str], list[str]]] = [
        (
            claim.id,
            content_terms(fold(claim.normalised_text)),
            list(claim.blind_evaluation.evidence_refs),
        )
        for claim in context.claims_for(article_id)
        if claim.blind_evaluation.evidence_refs
    ]

    assertions: list[_CausalAssertion] = []
    for sentence in sentences:
        if sentence.weight <= 0:
            continue
        if any(pattern.search(sentence.folded) for pattern in _CORRELATION_PATTERNS):
            continue
        matched: tuple[CausalCue, str, int, int] | None = None
        for cue, form, pattern in _CAUSAL_PATTERNS:
            hit = pattern.search(sentence.folded)
            if hit is not None:
                matched = (cue, form, hit.start(), hit.end())
                break
        if matched is None:
            continue
        cue, form, start, end = matched
        left = content_terms(sentence.folded[:start])
        right = content_terms(sentence.folded[end:])
        cause_terms, effect_terms = (left, right) if cue.cause_side == "before" else (right, left)

        backing_ref: str | None = None
        backing_why = ""
        for item in causal_evidence:
            item_terms = content_terms(fold(item.statement))
            if (
                overlap(cause_terms, item_terms) >= 0.34
                and overlap(effect_terms, item_terms) >= 0.34
            ):
                backing_ref, backing_why = (
                    item.id,
                    (
                        "an evidence item asserts the same causal link and shares terms with both "
                        "the cause and the effect clause"
                    ),
                )
                break
        if backing_ref is None:
            for claim_id, terms, refs in claim_terms:
                if overlap(sentence.terms, terms) >= 0.5 and refs:
                    backing_ref, backing_why = (
                        refs[0],
                        (
                            f"claim {claim_id} covers this sentence and its blind evaluation "
                            "cited evidence"
                        ),
                    )
                    break

        attributed = any(pattern.search(sentence.folded) for _, pattern in _ATTRIBUTION_PATTERNS)
        if backing_ref is not None:
            weight, status = 0.0, "evidence-backed"
        elif cue.hedged:
            weight, status = HEDGED_CAUSAL_WEIGHT, "hedged, unevidenced"
        elif attributed or sentence.in_quotation:
            weight, status = (
                ATTRIBUTED_CAUSAL_WEIGHT,
                "attributed to a source, not independently evidenced",
            )
        else:
            weight, status = 1.0, "asserted without evidence or attribution"
        assertions.append(
            _CausalAssertion(
                sentence=sentence,
                cue=cue,
                form=form,
                weight=weight,
                status=status,
                backing_ref=backing_ref,
                backing_reason=backing_why,
            )
        )

    total = len(assertions)
    unsupported_weight = sum(a.weight for a in assertions)
    raw = unsupported_weight / total if total else 0.0
    score = to_score(raw)

    backing_refs = sorted(
        {a.backing_ref for a in assertions if a.backing_ref and _is_ref(a.backing_ref)}
    )
    contributing = sorted(
        (a for a in assertions if a.weight > 0), key=lambda a: (-a.weight, a.sentence.index)
    )
    points = apportion(score, [a.weight for a in contributing])
    components = [
        Component(
            label=f"causal connective {a.form!r} — {a.status}",
            direction=_direction_of(point),
            weight=point,
            note=f"“{a.sentence.text}”",
        )
        for a, point in zip(contributing, points, strict=True)
    ]
    if not components and total:
        components = [
            Component(
                label=f"{total} causal assertion(s), all backed by an evidence item",
                direction=Direction.NONE,
                weight=0.0,
                evidence_refs=backing_refs,
                note="no unsupported causal language was found",
            )
        ]

    counter = [
        f"“{a.sentence.text}” — {a.backing_reason}" for a in assertions if a.backing_ref is not None
    ][:5]
    if not total:
        counter.append("the article makes no causal assertion")

    uncertainties: list[Uncertainty] = []
    if total and not context.evidence:
        uncertainties.append(
            Uncertainty(
                statement=(
                    "No evidence pool was supplied, so every causal assertion is recorded "
                    "as unbacked by default. This measures the absence of collected "
                    "evidence as much as the article's practice."
                ),
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by="running evidence collection before framing analysis",
            )
        )

    return DimensionResult(
        key=FramingDimensionKey.UNSUPPORTED_CAUSAL_LANGUAGE,
        score=score,
        polarity=Polarity.LOWER_IS_BETTER,
        components=tuple(components),
        evidence_refs=tuple(backing_refs),
        confidence=_confidence(
            0.25 if not context.evidence else min(0.8, 0.4 + 0.05 * len(causal_evidence)),
            basis=[
                _basis(
                    ConfidenceFactor.EVIDENCE_AGREEMENT,
                    ConfidenceEffect.RAISES if causal_evidence else ConfidenceEffect.LOWERS,
                    f"{len(causal_evidence)} evidence item(s) themselves assert a causal link",
                )
            ],
            limiting_factor=(
                "no evidence item in the pool asserts any causal link, so no causal claim "
                "could be confirmed as backed"
                if not causal_evidence
                else None
            ),
        ),
        rationale=(
            f"{len(contributing)} of {total} causal assertion(s) are not backed by an evidence "
            "item linking the asserted cause to the asserted effect. Correlation wording is "
            "excluded; hedged and attributed claims are counted at reduced weight."
        ),
        sentences=tuple(a.sentence for a in assertions),
        calculation=Calculation(
            formula="score = 100 · Σ unsupported_weight / count(causal assertions)",
            inputs={
                "causal_assertions": total,
                "unsupported_weight": round(unsupported_weight, 3),
                "hedged_weight": HEDGED_CAUSAL_WEIGHT,
                "attributed_weight": ATTRIBUTED_CAUSAL_WEIGHT,
            },
            steps=(
                f"found {total} causal connective(s) after excluding correlation wording",
                f"unsupported weight {unsupported_weight:.3f}",
                f"share {raw:.3f}",
            ),
            raw_value=round(raw, 4),
            score=score,
        ),
        uncertainties=tuple(uncertainties),
        counter_evidence=tuple(counter),
    )


# ---------------------------------------------------------------------------
# Dimension 4: opinion_as_fact
# ---------------------------------------------------------------------------

#: Genres whose readers already know they are reading argument. The dimension
#: still applies — the schema's rule is that an opinion column is measured on
#: whether opinion is *dressed as established fact*, not on containing opinion —
#: but the genre signal itself is worth this much mitigation.
_GENRE_DISCOUNT: Final[Mapping[ArticleType, float]] = {
    ArticleType.OPINION_COLUMN: 0.5,
    ArticleType.EDITORIAL: 0.5,
    ArticleType.ANALYSIS: 0.8,
}


def score_opinion_as_fact(
    subject: ArticleUnderAnalysis, sentences: Sequence[SentenceRef]
) -> DimensionResult:
    """Measure evaluative predicates asserted without attribution.

    A sentence contributes when it carries an evaluative or normative predicate
    ("is inadequate", "must", "hay que") *and* nothing hands that judgement to
    anyone: no attribution cue, no stance marker, not inside a quotation. That
    conjunction is the whole test. "The association called the measure
    inadequate" is reporting; "the measure is inadequate" in the outlet's own
    voice is not.

    Genre is mitigating but not exculpatory: an opinion column is discounted by
    :data:`_GENRE_DISCOUNT` because its reader knows they are reading argument,
    and it is still measured, because presenting a contested judgement in the
    grammar of settled fact misleads in any genre.
    """
    discount = _GENRE_DISCOUNT.get(subject.article.article_type, 1.0)
    flagged: list[tuple[SentenceRef, str]] = []
    attributed: list[tuple[SentenceRef, str]] = []
    evaluative_total = 0

    for sentence in sentences:
        if sentence.weight <= 0:
            continue
        predicate: str | None = None
        for form, pattern in _EVALUATIVE_PATTERNS:
            if pattern.search(sentence.folded):
                predicate = form
                break
        if predicate is None:
            continue
        evaluative_total += 1
        attribution = next(
            (form for form, pattern in _ATTRIBUTION_PATTERNS if pattern.search(sentence.folded)),
            None,
        )
        stance = next(
            (form for form, pattern in _STANCE_PATTERNS if pattern.search(sentence.folded)), None
        )
        if attribution or stance or sentence.in_quotation:
            attributed.append(
                (
                    sentence,
                    attribution or stance or "inside quotation marks",
                )
            )
        else:
            flagged.append((sentence, predicate))

    weighted = sum(s.weight for s, _ in flagged) * discount
    denominator = sum(s.weight for s in sentences if s.weight > 0) or 1.0
    # Rate of unattributed evaluative sentences per ten sentences of exposure.
    rate = weighted / denominator * 10.0
    raw = saturate(rate, half=1.5)
    score = to_score(raw)

    flagged.sort(key=lambda row: (-row[0].weight, row[0].index))
    points = apportion(score, [s.weight for s, _ in flagged])
    components = [
        Component(
            label=f"unattributed evaluative predicate {predicate!r} in {sentence.zone.value}",
            direction=_direction_of(point),
            weight=point,
            note=f"“{sentence.text}” — no attribution cue, no stance marker, not quoted",
        )
        for (sentence, predicate), point in zip(flagged, points, strict=True)
    ]

    counter = [
        f"“{sentence.text}” — evaluative but attributed via {cue!r}"
        for sentence, cue in attributed[:5]
    ]
    if evaluative_total == 0:
        counter.append("no evaluative or normative predicate was found in the article")
    if discount < 1.0:
        counter.append(
            f"genre is {subject.article.article_type.value}: the reader is on notice that the "
            f"piece argues, so the rate was discounted by {discount:g}"
        )

    return DimensionResult(
        key=FramingDimensionKey.OPINION_AS_FACT,
        score=score,
        polarity=Polarity.LOWER_IS_BETTER,
        components=tuple(components),
        evidence_refs=(),
        confidence=_confidence(
            0.7 if subject.has_body else 0.3,
            basis=[
                _basis(
                    ConfidenceFactor.RETRIEVAL_COMPLETENESS,
                    ConfidenceEffect.RAISES if subject.has_body else ConfidenceEffect.LOWERS,
                    "full body text available"
                    if subject.has_body
                    else "headline and standfirst only",
                ),
                _basis(
                    ConfidenceFactor.CLAIM_AMBIGUITY,
                    ConfidenceEffect.LOWERS,
                    "attribution can be carried by a preceding sentence that this "
                    "sentence-local test does not see",
                ),
            ],
            limiting_factor=(
                "attribution spanning more than one sentence is not detected, so some "
                "flagged sentences may be attributed in context"
            ),
        ),
        rationale=(
            f"{len(flagged)} of {evaluative_total} evaluative or normative sentence(s) carry no "
            "attribution, no stance marker and no quotation marks, and so are stated in the "
            "grammatical form of factual reporting."
        ),
        sentences=tuple(sentence for sentence, _ in flagged),
        calculation=Calculation(
            formula="score = 100 · (1 − 2^(−rate/1.5)), rate = Σ zone_weight(unattributed) · genre_discount / Σ zone_weight · 10",
            inputs={
                "evaluative_sentences": evaluative_total,
                "unattributed": len(flagged),
                "attributed": len(attributed),
                "genre_discount": discount,
                "rate_per_10_sentences": round(rate, 3),
            },
            steps=(
                f"{evaluative_total} sentence(s) carry an evaluative or normative predicate",
                f"{len(attributed)} of them are attributed, quoted or stance-marked",
                f"weighted unattributed exposure {weighted:.3f} over {denominator:.1f} → rate {rate:.3f}",
            ),
            raw_value=round(raw, 4),
            score=score,
        ),
        uncertainties=(
            (
                Uncertainty(
                    statement=(
                        "Attribution carried by an adjacent sentence is not detected; the test "
                        "is sentence-local."
                    ),
                    kind=UncertaintyKind.MEASUREMENT,
                    resolvable_by="discourse-level attribution resolution",
                ),
            )
            if flagged
            else ()
        ),
        counter_evidence=tuple(counter),
    )


# ---------------------------------------------------------------------------
# Dimension 5: context_omission
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    """A piece of context that existed and could have been reported."""

    ref: str
    text: str
    terms: frozenset[str]
    numbers: frozenset[str]
    materiality: float
    peers_reporting: int
    why_material: str


def build_context_candidates(context: FramingContext) -> tuple[ContextCandidate, ...]:
    """Assemble the context an article *could* have carried, weighted by materiality.

    Candidates come from the primary document's propositions and provisions.
    Materiality is raised by three checkable properties: the item carries a
    figure, the item is a carve-out or condition (omitting an exception is one of
    the commonest ways a true summary becomes false), and — decisively — how many
    other articles in the same cluster reported it.

    That last term is why this dimension is computed against the cluster and not
    in isolation. "Aleph thinks this mattered" is an opinion; "six of the seven
    other articles covering this story reported it and this one did not" is an
    observation, and it is one the article's editor can dispute on the record.
    """
    peer_terms: list[frozenset[str]] = []
    peer_numbers: list[frozenset[str]] = []
    for peer in context.peers:
        sentences = peer.zones()
        peer_terms.append(
            frozenset().union(*[s.terms for s in sentences]) if sentences else frozenset()
        )
        peer_numbers.append(
            frozenset().union(*[s.numbers for s in sentences]) if sentences else frozenset()
        )

    candidates: list[ContextCandidate] = []

    def _add(ref: str, text: str, base: float, why: str) -> None:
        folded = fold(text)
        terms = content_terms(folded)
        numbers = numeric_tokens(text)
        if len(terms) < 3:
            return
        reporting = sum(
            1
            for pt, pn in zip(peer_terms, peer_numbers, strict=True)
            if (numbers and numbers & pn) or overlap(terms, pt) >= 0.45
        )
        peer_share = reporting / len(context.peers) if context.peers else 0.0
        candidates.append(
            ContextCandidate(
                ref=ref,
                text=text,
                terms=terms,
                numbers=numbers,
                materiality=round(base + 1.5 * peer_share, 3),
                peers_reporting=reporting,
                why_material=(
                    f"{why}; reported by {reporting} of {len(context.peers)} other article(s) "
                    "in the cluster"
                    if context.peers
                    else why
                ),
            )
        )

    for proposition in context.propositions:
        base = 0.6
        why = "proposition of the primary document"
        if proposition.quantities or proposition.money:
            base += 0.5
            why += ", carries a figure"
        if proposition.scope and (proposition.scope.exceptions or proposition.scope.conditions):
            base += 0.5
            why += ", carries an exception or condition"
        if proposition.proposition_type is PropositionType.CONDITIONAL:
            base += 0.3
            why += ", conditional"
        _add(proposition.id, proposition.text, base, why)

    for provision in context.provisions:
        base = 0.5
        why = f"provision of type {provision.provision_type.value}"
        if provision.exceptions:
            base += 0.6
            why += f", carves out {len(provision.exceptions)} exception(s)"
        if provision.sunset_date:
            base += 0.3
            why += ", carries a sunset date"
        _add(provision.id, provision.title or provision.text, base, why)

    return tuple(candidates)


def score_context_omission(
    subject: ArticleUnderAnalysis,
    sentences: Sequence[SentenceRef],
    candidates: Sequence[ContextCandidate],
) -> DimensionResult:
    """Measure material context present in the record that this article omits.

    The score is the materiality-weighted share of available context the article
    does not mention:

        score = 100 · Σ materiality(omitted) / Σ materiality(all candidates)

    "Mention" is generous on purpose — a shared figure or 35% topical overlap
    with any sentence counts — because the finding must survive paraphrase. A
    false omission finding is worse than a missed one: it accuses an article of
    hiding something it in fact said differently.

    With no cluster peers the dimension still runs against the primary document
    alone, but every peer-derived materiality term is zero, the degraded mode is
    recorded as a limitation, and confidence is reduced. Aleph does not pretend
    that a document-only baseline is the same measurement.
    """
    article_numbers: frozenset[str] = (
        frozenset().union(*[s.numbers for s in sentences]) if sentences else frozenset()
    )
    omitted: list[ContextCandidate] = []
    covered: list[ContextCandidate] = []
    for candidate in candidates:
        mentioned = bool(candidate.numbers & article_numbers) or any(
            overlap(candidate.terms, s.terms) >= 0.35 for s in sentences
        )
        (covered if mentioned else omitted).append(candidate)

    total_materiality = sum(c.materiality for c in candidates)
    omitted_materiality = sum(c.materiality for c in omitted)
    raw = omitted_materiality / total_materiality if total_materiality > 0 else 0.0
    score = to_score(raw)

    omitted.sort(key=lambda c: (-c.materiality, c.ref))
    shown, rest = omitted[:8], omitted[8:]
    weights = [c.materiality for c in shown] + ([sum(c.materiality for c in rest)] if rest else [])
    points = apportion(score, weights)
    components = [
        Component(
            label=f"omitted: {candidate.text[:110]}",
            direction=_direction_of(point),
            weight=point,
            evidence_refs=[candidate.ref] if _is_ref(candidate.ref) else [],
            note=candidate.why_material,
        )
        for candidate, point in zip(shown, points, strict=False)
    ]
    if rest:
        components.append(
            Component(
                label=f"{len(rest)} further omitted item(s) of lower materiality",
                direction=_direction_of(points[-1]),
                weight=points[-1],
                evidence_refs=[c.ref for c in rest[:20] if _is_ref(c.ref)],
                note="; ".join(c.text[:60] for c in rest[:5]),
            )
        )

    counter = [f"reported: {c.text[:110]}" for c in covered[:5]]
    if not candidates:
        counter.append(
            "no primary propositions or provisions were supplied, so nothing could be "
            "identified as omitted"
        )

    has_peer_baseline = any(c.peers_reporting > 0 for c in candidates)
    uncertainties: list[Uncertainty] = []
    if not has_peer_baseline:
        uncertainties.append(
            Uncertainty(
                statement=(
                    "No other articles from the cluster were available, so materiality rests "
                    "on the primary document alone rather than on what other coverage "
                    "actually reported."
                ),
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by="supplying the rest of the news cluster",
            )
        )
    if omitted:
        uncertainties.append(
            Uncertainty(
                statement=(
                    "An article may legitimately omit context that is outside its stated "
                    "scope; this measure does not read scope."
                ),
                kind=UncertaintyKind.OUT_OF_SCOPE,
                resolvable_by="comparing against articles with the same declared scope",
            )
        )

    has_peers = has_peer_baseline
    return DimensionResult(
        key=FramingDimensionKey.CONTEXT_OMISSION,
        score=score,
        polarity=Polarity.LOWER_IS_BETTER,
        components=tuple(components),
        evidence_refs=tuple(sorted({c.ref for c in omitted if _is_ref(c.ref)})[:40]),
        confidence=_confidence(
            0.0 if not candidates else (0.75 if has_peers else 0.4),
            basis=[
                _basis(
                    ConfidenceFactor.PRIMARY_SOURCE_COVERAGE,
                    ConfidenceEffect.RAISES if candidates else ConfidenceEffect.LOWERS,
                    f"{len(candidates)} candidate context item(s) drawn from the primary document",
                ),
                _basis(
                    ConfidenceFactor.RETRIEVAL_COMPLETENESS,
                    ConfidenceEffect.RAISES if has_peers else ConfidenceEffect.LOWERS,
                    "cluster peers available as a reporting baseline"
                    if has_peers
                    else "no cluster peers: materiality is document-derived only",
                ),
            ],
            limiting_factor=(
                "no primary document material was supplied"
                if not candidates
                else (None if has_peers else "no cluster peers to establish what was reportable")
            ),
        ),
        rationale=(
            f"{len(omitted)} of {len(candidates)} available context item(s) are not mentioned "
            f"by this article, carrying {omitted_materiality:.2f} of "
            f"{total_materiality:.2f} total materiality. Materiality rises with figures, "
            "carve-outs, and how many other articles in the cluster reported the item."
        ),
        sentences=(),
        calculation=Calculation(
            formula="score = 100 · Σ materiality(omitted) / Σ materiality(all candidates)",
            inputs={
                "candidates": len(candidates),
                "omitted": len(omitted),
                "covered": len(covered),
                "omitted_materiality": round(omitted_materiality, 3),
                "total_materiality": round(total_materiality, 3),
            },
            steps=(
                f"assembled {len(candidates)} candidate context item(s)",
                f"{len(covered)} matched a sentence of this article by figure or 35% term overlap",
                f"omitted share by materiality = {raw:.4f}",
            ),
            raw_value=round(raw, 4),
            score=score,
        ),
        uncertainties=tuple(uncertainties),
        counter_evidence=tuple(counter),
    )


# ---------------------------------------------------------------------------
# Dimension 6: selection_asymmetry
# ---------------------------------------------------------------------------


def _total_variation(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    """Total-variation distance between two distributions over the same keys.

    Zero when the article's mix matches the document's mix, one when they are
    disjoint. A distance measure rather than a directional one on purpose: this
    dimension reports that selection is uneven, never which side the unevenness
    favours, because "favours" would require the political reading Aleph refuses.
    """
    keys = set(left) | set(right)
    lt, rt = sum(left.values()), sum(right.values())
    if lt <= 0 or rt <= 0:
        return 0.0
    return 0.5 * sum(abs(left.get(k, 0.0) / lt - right.get(k, 0.0) / rt) for k in keys)


def score_selection_asymmetry(
    subject: ArticleUnderAnalysis,
    sentences: Sequence[SentenceRef],
    context: FramingContext,
) -> DimensionResult:
    """Measure how unevenly the article selects from the material available.

    Four sub-measures, each a total-variation distance between what the article
    used and what existed, each contributing its own component:

    * **figures** — the mix of monetary roles the article cites versus the mix
      the document contains. An article quoting only costs from a document that
      states costs and allocations has selected;
    * **provisions** — the mix of mechanism types mentioned versus present;
    * **voices** — distinct quoted *roles* here versus distinct roles across the
      cluster. Roles, never parties: diversity of evidence, not of affiliation;
    * **evidence stance** — whether the cited evidence is drawn only from items
      that support, or only from items that contradict, the same targets.

    A sub-measure with no baseline is dropped and its weight redistributed, and
    the drop is published as an uncertainty. Quoting one side more is only
    asymmetric if the other side's material existed, so a missing baseline must
    lower the measurement's reach rather than raise its score.
    """
    article_numbers: frozenset[str] = (
        frozenset().union(*[s.numbers for s in sentences]) if sentences else frozenset()
    )
    subs: list[tuple[str, float, float, str]] = []  # (label, weight, value 0-1, note)
    dropped: list[str] = []

    # --- figures ---------------------------------------------------------
    if context.monetary_values:
        doc_mix: dict[str, float] = {}
        art_mix: dict[str, float] = {}
        cited = 0
        for value in context.monetary_values:
            doc_mix[value.role.value] = doc_mix.get(value.role.value, 0.0) + 1.0
            if numeric_tokens(str(value.money.amount)) & article_numbers:
                art_mix[value.role.value] = art_mix.get(value.role.value, 0.0) + 1.0
                cited += 1
        if cited:
            subs.append(
                (
                    "figure selection",
                    0.30,
                    _total_variation(art_mix, doc_mix),
                    f"article cites {cited} of {len(context.monetary_values)} document figures; "
                    f"article role mix {dict(sorted(art_mix.items()))} vs document "
                    f"{dict(sorted(doc_mix.items()))}",
                )
            )
        else:
            dropped.append("figure selection (the article cites none of the document's figures)")
    else:
        dropped.append("figure selection (no monetary values extracted from the document)")

    # --- provisions ------------------------------------------------------
    if context.provisions:
        doc_mech: dict[str, float] = {}
        art_mech: dict[str, float] = {}
        mentioned = 0
        for provision in context.provisions:
            key = (provision.mechanism_type or provision.provision_type).value
            doc_mech[key] = doc_mech.get(key, 0.0) + 1.0
            terms = content_terms(fold(provision.title or provision.text))
            if any(overlap(terms, s.terms) >= 0.35 for s in sentences):
                art_mech[key] = art_mech.get(key, 0.0) + 1.0
                mentioned += 1
        if mentioned:
            subs.append(
                (
                    "provision selection",
                    0.25,
                    _total_variation(art_mech, doc_mech),
                    f"article touches {mentioned} of {len(context.provisions)} provisions; "
                    f"mechanism mix {dict(sorted(art_mech.items()))} vs document "
                    f"{dict(sorted(doc_mech.items()))}",
                )
            )
        else:
            dropped.append("provision selection (no provision of the document was recognised)")
    else:
        dropped.append("provision selection (no provisions supplied)")

    # --- voices ----------------------------------------------------------
    here_roles = {q.speaker_role for q in subject.article.quotations if q.speaker_role}
    cluster_roles: set[str] = set(here_roles)
    for peer in context.peers:
        cluster_roles |= {q.speaker_role for q in peer.article.quotations if q.speaker_role}
    if cluster_roles and context.peers:
        share = len(here_roles) / len(cluster_roles)
        subs.append(
            (
                "voice selection",
                0.30,
                max(0.0, 1.0 - share),
                f"{len(here_roles)} of the {len(cluster_roles)} distinct speaker roles quoted "
                f"anywhere in the cluster appear here: {sorted(here_roles)}",
            )
        )
    else:
        dropped.append(
            "voice selection (no cluster peers, so the set of available roles is unknown)"
        )

    # --- evidence stance -------------------------------------------------
    supporting = sum(1 for item in context.evidence if item.supports)
    contradicting = sum(1 for item in context.evidence if item.contradicts)
    cited_support = 0
    cited_contra = 0
    evidence_index = context.evidence_by_id()
    for claim in context.claims_for(subject.article.id):
        for ref in claim.blind_evaluation.evidence_refs:
            item = evidence_index.get(ref)
            if item is None:
                continue
            cited_support += 1 if item.supports else 0
            cited_contra += 1 if item.contradicts else 0
    if (supporting or contradicting) and (cited_support or cited_contra):
        subs.append(
            (
                "evidence stance selection",
                0.15,
                _total_variation(
                    {"supports": float(cited_support), "contradicts": float(cited_contra)},
                    {"supports": float(supporting), "contradicts": float(contradicting)},
                ),
                f"article's claims cite {cited_support} supporting and {cited_contra} "
                f"contradicting item(s) from a pool of {supporting} and {contradicting}",
            )
        )
    else:
        dropped.append("evidence stance selection (no evaluated claims cite pool evidence)")

    weight_sum = sum(w for _, w, _, _ in subs)
    raw = sum(w * v for _, w, v, _ in subs) / weight_sum if weight_sum > 0 else 0.0
    score = to_score(raw)

    points = apportion(score, [w * v for _, w, v, _ in subs])
    components = [
        Component(
            label=f"{label} (total-variation distance {value:.2f}, weight {weight:g})",
            direction=_direction_of(point),
            weight=point,
            note=note,
        )
        for (label, weight, value, note), point in zip(subs, points, strict=True)
    ]
    if not components:
        components = [
            Component(
                label="no baseline available for any sub-measure",
                direction=Direction.NONE,
                weight=0.0,
                note="; ".join(dropped),
            )
        ]

    return DimensionResult(
        key=FramingDimensionKey.SELECTION_ASYMMETRY,
        score=score,
        polarity=Polarity.LOWER_IS_BETTER,
        components=tuple(components),
        evidence_refs=(),
        confidence=_confidence(
            min(0.8, 0.2 * len(subs)),
            basis=[
                _basis(
                    ConfidenceFactor.RETRIEVAL_COMPLETENESS,
                    ConfidenceEffect.RAISES if len(subs) >= 3 else ConfidenceEffect.LOWERS,
                    f"{len(subs)} of 4 sub-measures had a baseline to compare against",
                )
            ],
            limiting_factor="; ".join(dropped) if dropped else None,
        ),
        rationale=(
            f"{len(subs)} of 4 sub-measures could be computed. The score is their "
            "weight-normalised mean distance between what the article used and what the "
            "document, the cluster and the evidence pool contained. It reports that "
            "selection is uneven, never which side the unevenness favours."
        ),
        sentences=(),
        calculation=Calculation(
            formula="score = 100 · Σ(weight · total_variation) / Σ weight, over available sub-measures",
            inputs={
                "sub_measures_available": len(subs),
                "sub_measures_dropped": len(dropped),
                "weight_sum": round(weight_sum, 3),
            },
            steps=tuple(
                f"{label}: distance {value:.3f} × weight {weight:g}"
                for label, weight, value, _ in subs
            )
            or ("no sub-measure could be computed",),
            raw_value=round(raw, 4),
            score=score,
        ),
        uncertainties=tuple(
            Uncertainty(
                statement=f"Sub-measure dropped: {reason}.",
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by="supplying the missing baseline",
            )
            for reason in dropped
        ),
        counter_evidence=tuple(
            f"{label}: distance {value:.2f} — {note}"
            for label, _, value, note in subs
            if value < 0.2
        ),
    )


# ---------------------------------------------------------------------------
# Dimension 7: source_diversity
# ---------------------------------------------------------------------------

#: Distinct independent sources at which the score reaches 50.
SOURCE_DIVERSITY_HALF: Final[float] = 2.5

#: Ceiling applied when only the headline and standfirst were available. A piece
#: whose body was not retrieved cannot demonstrate sourcing, and scoring it as
#: though it had none would punish a retrieval failure as an editorial one.
HEADLINE_ONLY_DIVERSITY_CAP: Final[int] = 40


def score_source_diversity(
    subject: ArticleUnderAnalysis,
    context: FramingContext,
    independence: IndependenceAnalysis | None,
) -> DimensionResult:
    """Count distinct *independent* sources the article draws on.

    Candidate sources are gathered from three places — the roles quoted, the
    primary-source grounding entries, and the evidence items cited by claims
    extracted from this article — and then **collapsed**. Two collapses run:
    evidence items that restate another item fold into their root via
    ``derived_from_evidence_id``, and any source traced by
    :class:`IndependenceAnalysis` to a syndication chain or shared-origin group
    folds onto that group's origin.

    The collapse is the point. Five quotations from one briefing are one source
    and forty outlets carrying one wire story are one observation; a diversity
    score that counted them as five and forty would reward volume and call it
    corroboration. When no independence analysis is available the raw count is
    used, the failure to collapse is stated, and confidence drops — Aleph never
    assumes independence it has not checked.
    """
    raw_keys: dict[str, str] = {}

    for quotation in subject.article.quotations:
        if quotation.speaker_role:
            raw_keys[f"role:{quotation.speaker_role.strip().lower()}"] = (
                f"quoted role {quotation.speaker_role!r}"
            )
    for entry in subject.article.primary_source_grounding:
        raw_keys[entry.ref] = f"grounding reference ({entry.kind.value})"

    by_id = context.evidence_by_id()
    for claim in context.claims_for(subject.article.id):
        for ref in claim.blind_evaluation.evidence_refs:
            item = by_id.get(ref)
            if item is None:
                raw_keys[ref] = "evidence cited by a claim of this article"
                continue
            root = item
            seen = {root.id}
            while root.derived_from_evidence_id and root.derived_from_evidence_id not in seen:
                parent = by_id.get(root.derived_from_evidence_id)
                if parent is None:
                    break
                seen.add(parent.id)
                root = parent
            raw_keys[root.source_ref.id] = f"source of evidence {item.id}" + (
                f" (restates {root.id})" if root.id != item.id else ""
            )

    origins = _origin_map(independence)
    collapsed: dict[str, list[str]] = {}
    for key in sorted(raw_keys):
        canonical = origins.get(key, key)
        collapsed.setdefault(canonical, []).append(key)

    distinct = len(collapsed)
    raw = saturate(float(distinct), half=SOURCE_DIVERSITY_HALF)
    score = to_score(raw)

    capped = False
    if not subject.has_body and score > HEADLINE_ONLY_DIVERSITY_CAP:
        score = HEADLINE_ONLY_DIVERSITY_CAP
        capped = True

    ordered = sorted(collapsed.items(), key=lambda kv: kv[0])
    points = apportion(score, [1.0 for _ in ordered])
    components = [
        Component(
            label=f"independent source: {canonical}",
            direction=_direction_of(point),
            weight=point,
            evidence_refs=[canonical] if _is_ref(canonical) else [],
            note="; ".join(raw_keys[member] for member in members)
            + (
                f" — collapsed {len(members)} reference(s) onto one origin"
                if len(members) > 1
                else ""
            ),
        )
        for (canonical, members), point in zip(ordered, points, strict=True)
    ]
    if not components:
        components = [
            Component(
                label="no identifiable source",
                direction=Direction.NONE,
                weight=0.0,
                note=(
                    "the article quotes no role, points at no primary source, and no claim "
                    "extracted from it cites evidence"
                ),
            )
        ]

    collapsed_count = sum(len(m) - 1 for m in collapsed.values())
    counter: list[str] = []
    if independence is not None:
        counter.append(
            f"cluster independence analysis reports {independence.distinct_original_sources} "
            f"distinct original source(s) across {independence.total_articles} article(s) and "
            f"{independence.independent_corroboration_count} independent corroboration(s)"
        )
    if collapsed_count:
        counter.append(
            f"{collapsed_count} apparent source(s) collapsed onto an origin they reproduce"
        )
    if capped:
        counter.append(
            f"score capped at {HEADLINE_ONLY_DIVERSITY_CAP} because the body was unavailable: "
            "a piece whose text was not retrieved cannot demonstrate its sourcing"
        )

    uncertainties: list[Uncertainty] = []
    if independence is None:
        uncertainties.append(
            Uncertainty(
                statement=(
                    "No independence analysis was available, so syndicated or derivative "
                    "sources could not be collapsed and this count may overstate how much "
                    "was independently observed."
                ),
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by="running the cluster independence analysis",
            )
        )
    if not subject.has_body:
        uncertainties.append(
            Uncertainty(
                statement="Only headline and standfirst were available; in-text sourcing is unseen.",
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by="retrieving the article body",
            )
        )

    return DimensionResult(
        key=FramingDimensionKey.SOURCE_DIVERSITY,
        score=score,
        polarity=Polarity.HIGHER_IS_BETTER,
        components=tuple(components),
        evidence_refs=tuple(sorted(k for k in collapsed if _is_ref(k))),
        confidence=_confidence(
            (0.75 if independence is not None else 0.4) * (1.0 if subject.has_body else 0.5),
            basis=[
                _basis(
                    ConfidenceFactor.SOURCE_INDEPENDENCE,
                    ConfidenceEffect.RAISES
                    if independence is not None
                    else ConfidenceEffect.LOWERS,
                    "syndication collapse applied"
                    if independence is not None
                    else "no independence analysis: duplicates may be counted separately",
                ),
                _basis(
                    ConfidenceFactor.RETRIEVAL_COMPLETENESS,
                    ConfidenceEffect.RAISES if subject.has_body else ConfidenceEffect.LOWERS,
                    "full body text available" if subject.has_body else "metadata only",
                ),
            ],
            limiting_factor=(
                "no independence analysis available to collapse syndicated sources"
                if independence is None
                else None
            ),
        ),
        rationale=(
            f"{distinct} distinct source(s) after collapsing {collapsed_count} reference(s) "
            f"onto origins they reproduce, from {len(raw_keys)} raw reference(s). Distinctness "
            "means distinct observation, not distinct affiliation."
        ),
        sentences=(),
        calculation=Calculation(
            formula="score = 100 · (1 − 2^(−distinct/2.5)), capped at 40 when no body text was available",
            inputs={
                "raw_references": len(raw_keys),
                "distinct_after_collapse": distinct,
                "collapsed": collapsed_count,
                "half": SOURCE_DIVERSITY_HALF,
                "body_available": str(subject.has_body),
            },
            steps=(
                f"gathered {len(raw_keys)} raw source reference(s)",
                f"collapsed {collapsed_count} onto an origin",
                f"saturating {distinct} at half {SOURCE_DIVERSITY_HALF:g} → {raw:.3f}",
            )
            + ((f"capped at {HEADLINE_ONLY_DIVERSITY_CAP} (no body text)",) if capped else ()),
            raw_value=round(raw, 4),
            score=score,
        ),
        uncertainties=tuple(uncertainties),
        counter_evidence=tuple(counter),
    )


# ---------------------------------------------------------------------------
# Dimension 8: primary_source_grounding
# ---------------------------------------------------------------------------

#: What a tier of source can anchor a factual claim *to*. This is not a
#: credibility ranking: it is how close the reader gets to material they could
#: check for themselves. A statistical dataset is not more honest than an expert
#: analysis; it is more directly checkable.
_TIER_GROUNDING: Final[Mapping[EvidenceTier, float]] = {
    EvidenceTier.PRIMARY_DOCUMENT: 1.0,
    EvidenceTier.LEGISLATIVE_RECORD: 0.95,
    EvidenceTier.STATISTICAL_DATASET: 0.85,
    EvidenceTier.OFFICIAL_TECHNICAL_REPORT: 0.85,
    EvidenceTier.PEER_REVIEWED: 0.7,
    EvidenceTier.EXPERT_ANALYSIS: 0.5,
    EvidenceTier.JOURNALISM: 0.3,
    EvidenceTier.POLITICAL_STATEMENT: 0.15,
    EvidenceTier.SOCIAL_MEDIA: 0.05,
}

#: How firmly each grounding gesture actually points. Naming a report without
#: pointing at it asks the reader to take the outlet's word for what the report
#: says, which is the substitution of authority for evidence Aleph refuses.
_GROUNDING_KIND_WEIGHT: Final[Mapping[GroundingKind, float]] = {
    GroundingKind.LINKED: 1.0,
    GroundingKind.QUOTED_DIRECTLY: 0.95,
    GroundingKind.PARAPHRASED: 0.7,
    GroundingKind.NAMED_WITHOUT_LINK: 0.45,
    GroundingKind.NONE: 0.0,
}


def score_primary_source_grounding(
    subject: ArticleUnderAnalysis, context: FramingContext
) -> DimensionResult:
    """Measure the fraction of the article's factual claims traceable to primary material.

    Two independent signals, combined at 0.65 / 0.35 when both are present and
    renormalised when only one is:

    * **claim traceability** — for each claim extracted from this article whose
      statement type is ``fact``: 1.0 if it carries a proposition reference back
      into the primary text, otherwise the best :data:`_TIER_GROUNDING` weight
      among the evidence its blind evaluation cited, otherwise 0;
    * **grounding gestures** — the article's own
      ``primary_source_grounding`` entries, weighted by
      :data:`_GROUNDING_KIND_WEIGHT`.

    Forecasts, opinions and normative statements are excluded from the
    denominator. Grading an article for failing to source a prediction to a
    primary document would penalise it for the honest form of a statement about
    the future.
    """
    claims = [
        claim
        for claim in context.claims_for(subject.article.id)
        if claim.statement_type is StatementType.FACT
    ]
    by_id = context.evidence_by_id()
    traceable: list[tuple[Claim, float, str, list[str]]] = []
    for claim in claims:
        if claim.proposition_refs:
            traceable.append(
                (
                    claim,
                    1.0,
                    "traced to the primary text via proposition reference",
                    list(claim.proposition_refs),
                )
            )
            continue
        best, best_ref, best_tier = 0.0, None, None
        for ref in claim.blind_evaluation.evidence_refs:
            item = by_id.get(ref)
            if item is None:
                continue
            weight = _TIER_GROUNDING.get(item.tier, 0.2)
            if weight > best:
                best, best_ref, best_tier = weight, ref, item.tier
        traceable.append(
            (
                claim,
                best,
                (
                    f"best available anchor is a {best_tier.value} item"
                    if best_tier is not None
                    else "no evidence item cited by the blind evaluation"
                ),
                [best_ref] if best_ref else [],
            )
        )

    gestures = [
        (entry, _GROUNDING_KIND_WEIGHT.get(entry.kind, 0.0))
        for entry in subject.article.primary_source_grounding
    ]

    parts: list[tuple[str, float, float]] = []  # (label, weight, value)
    if traceable:
        parts.append(
            ("claim traceability", 0.65, sum(v for _, v, _, _ in traceable) / len(traceable))
        )
    if gestures:
        parts.append(("grounding gestures", 0.35, sum(w for _, w in gestures) / len(gestures)))
    weight_sum = sum(w for _, w, _ in parts)
    raw = sum(w * v for _, w, v in parts) / weight_sum if weight_sum > 0 else 0.0
    score = to_score(raw)

    contributors = sorted(traceable, key=lambda row: (-row[1], row[0].id))
    weights = [w * v for _, w, v in parts]
    part_points = apportion(score, weights)
    components: list[Component] = []
    for (label, weight, value), point in zip(parts, part_points, strict=True):
        detail = (
            "; ".join(
                f"{claim.id}: {value_:.2f} ({why})" for claim, value_, why, _ in contributors[:6]
            )
            if label == "claim traceability"
            else "; ".join(f"{entry.ref} ({entry.kind.value})" for entry, _ in gestures[:6])
        )
        components.append(
            Component(
                label=f"{label}: mean {value:.2f} (weight {weight:g})",
                direction=_direction_of(point),
                weight=point,
                evidence_refs=sorted(
                    {ref for _, _, _, refs in contributors for ref in refs if _is_ref(ref)}
                    if label == "claim traceability"
                    else {entry.ref for entry, _ in gestures if _is_ref(entry.ref)}
                )[:20],
                note=detail,
            )
        )
    if not components:
        components = [
            Component(
                label="no factual claims and no grounding entries",
                direction=Direction.NONE,
                weight=0.0,
                note=(
                    "nothing in this article was extracted as a checkable factual claim and "
                    "the article points at no primary source"
                ),
            )
        ]

    ungrounded = [c for c, v, _, _ in traceable if v <= 0.0]
    counter = [
        f"{claim.id} anchored at {value:.2f}: {why}"
        for claim, value, why, _ in contributors[:5]
        if value > 0
    ]
    if not claims:
        counter.append("no factual claims were extracted from this article")

    return DimensionResult(
        key=FramingDimensionKey.PRIMARY_SOURCE_GROUNDING,
        score=score,
        polarity=Polarity.HIGHER_IS_BETTER,
        components=tuple(components),
        evidence_refs=tuple(
            sorted({ref for _, _, _, refs in traceable for ref in refs if _is_ref(ref)})[:40]
        ),
        confidence=_confidence(
            0.0 if not parts else min(0.8, 0.35 + 0.08 * len(claims)),
            basis=[
                _basis(
                    ConfidenceFactor.PRIMARY_SOURCE_COVERAGE,
                    ConfidenceEffect.RAISES if traceable else ConfidenceEffect.LOWERS,
                    f"{len(claims)} factual claim(s) extracted from this article",
                )
            ],
            limiting_factor=(
                "no factual claims were extracted, so traceability could not be measured"
                if not claims
                else None
            ),
        ),
        rationale=(
            f"{len(claims) - len(ungrounded)} of {len(claims)} factual claim(s) trace to primary "
            f"or official material, and the article makes {len(gestures)} explicit grounding "
            "gesture(s). Forecasts and opinions are excluded from the denominator."
        ),
        sentences=(),
        calculation=Calculation(
            formula="score = 100 · Σ(weight · mean_anchor) / Σ weight over available signals",
            inputs={
                "factual_claims": len(claims),
                "ungrounded_claims": len(ungrounded),
                "grounding_entries": len(gestures),
                "signals_available": len(parts),
            },
            steps=tuple(
                f"{label}: mean {value:.3f} × weight {weight:g}" for label, weight, value in parts
            )
            or ("no signal available",),
            raw_value=round(raw, 4),
            score=score,
        ),
        uncertainties=(
            (
                Uncertainty(
                    statement=(
                        "No factual claims were extracted from this article, so grounding "
                        "rests on the article's own declared references."
                    ),
                    kind=UncertaintyKind.MISSING_EVIDENCE,
                    resolvable_by="running claim extraction over this article",
                ),
            )
            if not claims
            else ()
        ),
        counter_evidence=tuple(counter),
    )


# ---------------------------------------------------------------------------
# The analysis object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FramingAnalysis:
    """Eight results and no ninth number.

    There is deliberately no ``overall_score``, no ``bias`` and no arithmetic
    that would produce one. :meth:`pattern_note` describes the shape of the
    profile in words — "strong primary-source grounding alongside consistently
    one-sided source selection" — which is the honest summary, because the eight
    dimensions are not commensurable: six are faults, two are merits, and adding
    a merit to a fault yields a number whose only available reading is a
    political one.
    """

    article_id: str
    profile_version: str
    results: Mapping[FramingDimensionKey, DimensionResult]
    limitations: tuple[str, ...] = ()
    confidence: Confidence | None = None

    def explain(self, dimension: FramingDimensionKey | str) -> DimensionResult:
        """Return the full record behind one dimension.

        The evidence, the sentences involved, the calculation, the uncertainty
        and the counter-evidence — as data. Nothing here judges, bands or
        colours a score; an interface decides how to present it, using the
        ``polarity`` field to avoid rendering a merit as a fault.

        Raises:
            KeyError: If ``dimension`` is not one of the eight fixed keys.
        """
        key = FramingDimensionKey(dimension)
        return self.results[key]

    def pattern_note(self) -> str:
        """Describe the profile's *shape* without averaging it.

        Names the highest-scoring fault and the strongest merit, so a reader gets
        a sentence rather than a number and the sentence stays arguable.
        """
        faults = [
            (r.score, r.key.value)
            for r in self.results.values()
            if r.polarity is Polarity.LOWER_IS_BETTER
        ]
        merits = [
            (r.score, r.key.value)
            for r in self.results.values()
            if r.polarity is Polarity.HIGHER_IS_BETTER
        ]
        top_fault = max(faults) if faults else (0, "none")
        top_merit = max(merits) if merits else (0, "none")
        low_merit = min(merits) if merits else (0, "none")
        return (
            f"Highest lower-is-better dimension: {top_fault[1]} at {top_fault[0]}. "
            f"Strongest higher-is-better dimension: {top_merit[1]} at {top_merit[0]}; "
            f"weakest: {low_merit[1]} at {low_merit[0]}. These are not averaged: six of the "
            "eight are faults and two are merits, and no single figure summarises them."
        )

    def to_dimensions(self) -> FramingDimensions:
        """Render the eight results as the contract model."""
        return FramingDimensions(
            **{
                key.value: self.results[key].to_model()  # type: ignore[arg-type]
                for key in FramingDimensionKey
            }
        )

    def to_profile(self, profile_id: str, *, generated_at: str | None = None) -> FramingProfile:
        """Render the whole analysis as a :class:`FramingProfile`.

        Args:
            profile_id: A ``framing:`` id, normally from
                :func:`aleph.core.ids.framing_profile_id`. Passed in rather than
                minted here so id construction stays in one place.
            generated_at: UTC timestamp. Omitted rather than invented when the
                caller does not supply one; this module reads no clock, so two
                runs over the same inputs produce byte-identical output.
        """
        evidence_confidences = [r.confidence.evidence_confidence for r in self.results.values()]
        profile_confidence = self.confidence or _confidence(
            min(evidence_confidences) if evidence_confidences else 0.0,
            basis=[
                _basis(
                    ConfidenceFactor.RETRIEVAL_COMPLETENESS,
                    ConfidenceEffect.NEUTRAL,
                    "profile confidence is the minimum across the eight dimensions, not their "
                    "mean: the profile is only as trustworthy as its weakest measurement",
                )
            ],
            limiting_factor=(
                min(self.results.values(), key=lambda r: r.confidence.evidence_confidence).key.value
                if self.results
                else None
            ),
        )
        return FramingProfile(
            id=profile_id,
            article_id=self.article_id,
            profile_version=self.profile_version,
            generated_at=generated_at,
            dimensions=self.to_dimensions(),
            overall_note=self.pattern_note(),
            confidence=profile_confidence,
            limitations=list(self.limitations),
        )


def analyse_framing(
    subject: ArticleUnderAnalysis, context: FramingContext | None = None
) -> FramingAnalysis:
    """Compute all eight framing dimensions for one article.

    Each dimension is delegated to its own named function, which returns both a
    score and the record that produced it; this function only assembles them and
    collects the limitations that apply to the profile as a whole. It reads no
    clock, performs no I/O and makes no network call, so the same inputs always
    produce the same eight numbers.

    Args:
        subject: The article and whatever of its text was retrieved.
        context: What the article is measured against — the primary document's
            propositions and provisions, the evidence pool, the claims extracted
            from it, and the rest of its cluster. An empty context is legal and
            produces an honest, low-confidence profile in which the comparative
            dimensions state plainly that they had nothing to compare against.

    Returns:
        A :class:`FramingAnalysis`. It has eight scores and no aggregate.
    """
    ctx = context or FramingContext()
    sentences = subject.zones()
    sources = build_source_statements(ctx)
    candidates = build_context_candidates(ctx)
    independence = resolve_independence(ctx)

    results: dict[FramingDimensionKey, DimensionResult] = {
        FramingDimensionKey.LOADED_LANGUAGE: score_loaded_language(subject, sentences),
        FramingDimensionKey.CERTAINTY_INFLATION: score_certainty_inflation(
            subject, sentences, sources
        ),
        FramingDimensionKey.UNSUPPORTED_CAUSAL_LANGUAGE: score_unsupported_causal_language(
            sentences, ctx, subject.article.id
        ),
        FramingDimensionKey.OPINION_AS_FACT: score_opinion_as_fact(subject, sentences),
        FramingDimensionKey.CONTEXT_OMISSION: score_context_omission(
            subject, sentences, candidates
        ),
        FramingDimensionKey.SELECTION_ASYMMETRY: score_selection_asymmetry(subject, sentences, ctx),
        FramingDimensionKey.SOURCE_DIVERSITY: score_source_diversity(subject, ctx, independence),
        FramingDimensionKey.PRIMARY_SOURCE_GROUNDING: score_primary_source_grounding(subject, ctx),
    }

    limitations: list[str] = []
    if not subject.has_body:
        limitations.append(
            "Only the headline and standfirst were available; body-level wording, sourcing "
            "and attribution were not examined."
        )
    if not ctx.peers:
        limitations.append(
            "No other articles from the cluster were supplied, so context omission and voice "
            "selection were measured against the primary document alone."
        )
    if not ctx.evidence:
        limitations.append(
            "No evidence pool was supplied, so certainty inflation and causal support could "
            "not be checked against collected evidence."
        )
    if independence is None:
        limitations.append(
            "No independence analysis was available, so syndicated sources could not be "
            "collapsed and source diversity may be overstated."
        )
    language = (subject.article.language or "").lower()
    if language and not language.startswith(("es", "en")):
        limitations.append(
            f"The lexicons cover Spanish and English; this article is tagged {language!r}."
        )

    return FramingAnalysis(
        article_id=subject.article.id,
        profile_version=PROFILE_VERSION,
        results=results,
        limitations=tuple(limitations),
    )
