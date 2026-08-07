"""Warm phase 2 — decomposing a document into atomic, quotable propositions.

A policy document does not make one claim; it makes hundreds, welded together by
conjunctions, carve-outs and cross-references. That welding is where checking
goes wrong. "The levy rises to 4% and small enterprises are exempt until 2029"
is a single sentence carrying three separable assertions, and a system that
evaluates it as a unit must return one verdict for a statement that is partly
true, partly conditional and partly about a date. The verdict will be defensible
in the abstract and useless in particular. This module exists to prevent that: it
breaks a document down until each fragment says exactly one thing, and refuses to
emit anything it cannot quote.

Three rules are enforced structurally rather than encouraged.

**Nothing is published that cannot be quoted.** Every proposition carries a
:class:`~aleph.core.models.GroundedProvenance` whose span holds a *verbatim*
substring of the source, located by character offset wherever phase 1 gave us
offsets to work from. Candidates that cannot be tied back to a passage — most
often paraphrases invented by a language model — are discarded, not downgraded to
low confidence. A low-confidence unquotable assertion still reaches a reader; a
discarded one does not.

**Qualifiers are lifted out of the prose.** Negation, conditions, exceptions,
temporal bounds and modality live in their own fields. Free text loses a "not",
an "unless" or a "from 2029" first, and each of those inverts or voids the
statement. Holding them separately lets a later check ask "is this true *within
its stated scope*?" rather than the unanswerable "is this true?".

**The pipeline never hard-depends on a model.** :class:`RuleBasedExtractor` is a
complete, deterministic implementation that needs no network and no credentials;
:class:`LLMPropositionExtractor` is strictly additive, subject to the same
grounding gate, and falls back per-provision to the rule-based path whenever the
model returns nothing usable. A run with no provider configured is a normal run,
not a degraded one — which matters because a system that silently produces less
when the model is down produces silence that reads as an absence of content.

The module is document-agnostic. Its only language-specific content is
:class:`LinguisticProfile`: sets of function words (connectives, negations,
modals, hedges) for the scripts Aleph is likely to meet, plus a language-neutral
fallback that segments on punctuation alone. No jurisdiction, institution,
subject matter or named document appears anywhere in it.
"""

from __future__ import annotations

import json
import re
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final, Protocol, runtime_checkable

from aleph.core.enums import (
    ConfidenceEffect,
    ConfidenceFactor,
    DataStatus,
    ExtractionQualityState,
    Modality,
    PropositionType,
    ProvenanceSourceKind,
    ProvisionType,
    QuantityKind,
    StatementType,
)
from aleph.core.errors import ProviderError
from aleph.core.ids import proposition_id
from aleph.core.models import (
    SCHEMA_VERSION,
    Confidence,
    ConfidenceBasis,
    DocumentModel,
    GroundedProvenance,
    Negation,
    Proposition,
    PropositionCoverage,
    PropositionScope,
    PropositionSet,
    Provision,
    Quantity,
    Span,
)

__all__ = [
    "EXTRACTOR_VERSION",
    "LinguisticProfile",
    "GENERIC_PROFILE",
    "LANGUAGE_PROFILES",
    "profile_for_language",
    "profile_for_text",
    "TextUnit",
    "segment_units",
    "split_sentences",
    "locate_verbatim",
    "parse_number",
    "CompletionProvider",
    "PropositionExtractor",
    "RuleBasedExtractor",
    "LLMPropositionExtractor",
    "LLM_PROPOSITION_SCHEMA",
    "extract_propositions",
]

#: Version of this extractor. Recorded in every :class:`PropositionSet` so that a
#: change here invalidates a stored set rather than silently altering its meaning.
EXTRACTOR_VERSION: Final[str] = "1.0.0"

_MIN_UNIT_CHARS: Final[int] = 12
"""Below this, a fragment is punctuation debris rather than a statement."""

_MIN_CLAUSE_TOKENS: Final[int] = 4
"""A coordinator only splits when both sides could stand as statements."""


# ---------------------------------------------------------------------------
# Linguistic profiles
#
# Function words, not subject matter. A profile tells the segmenter where a
# clause can be cut and tells the classifier which cues mark a duty, a denial or
# a hedge. Adding a language is adding data here; nothing downstream branches on
# which profile was used.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LinguisticProfile:
    """Cue vocabularies for one language, or the language-neutral fallback.

    Every field is a set of *function* words. None of them names a topic, a
    place or an institution, so a profile can be applied to any document written
    in that language without importing assumptions about what the document is
    about. The fallback profile (:data:`GENERIC_PROFILE`) carries empty cue sets
    and therefore segments on punctuation only: it under-splits rather than
    mis-splitting, which is the correct direction for a system whose output is
    quoted back to readers.
    """

    code: str
    clause_coordinators: tuple[str, ...] = ()
    """Words that may join two independent statements inside one sentence."""
    conditional_cues: tuple[str, ...] = ()
    exception_cues: tuple[str, ...] = ()
    negation_cues: tuple[str, ...] = ()
    obligation_cues: tuple[str, ...] = ()
    permission_cues: tuple[str, ...] = ()
    prohibition_cues: tuple[str, ...] = ()
    proposal_cues: tuple[str, ...] = ()
    hedge_cues: tuple[str, ...] = ()
    temporal_cues: tuple[str, ...] = ()
    duration_units: tuple[str, ...] = ()
    anaphora_openers: tuple[str, ...] = ()
    """Openers whose referent lives in a previous sentence. A unit starting with
    one of these is not self-contained until the referent is restored."""
    stopwords: frozenset[str] = frozenset()
    """Function words, used for phrase mining and for language detection. Shared
    with :mod:`aleph.retrieval.vocabulary`, which mines phrases from the same
    text and must not treat 'of the' as a retrieval term."""


GENERIC_PROFILE: Final[LinguisticProfile] = LinguisticProfile(code="und")
"""Language-neutral fallback: punctuation-only segmentation, no cue detection.

Chosen deliberately over guessing. A wrongly-applied modal cue would report a
discretion as a duty, which is a substantive misreading of an instrument; an
unsplit sentence is merely a coarser proposition, flagged ``is_atomic=False``.
"""


LANGUAGE_PROFILES: Final[dict[str, LinguisticProfile]] = {
    "en": LinguisticProfile(
        code="en",
        clause_coordinators=("and", "but", "while", "whereas", "however", "although", "though"),
        conditional_cues=(
            "if",
            "unless",
            "provided that",
            "in the event that",
            "where",
            "when",
            "subject to",
            "conditional on",
            "once",
        ),
        exception_cues=(
            "except",
            "excluding",
            "other than",
            "save for",
            "with the exception of",
            "does not apply to",
            "shall not apply to",
        ),
        negation_cues=("not", "no", "never", "neither", "nor", "without", "cannot", "may not"),
        obligation_cues=("shall", "must", "is required to", "are required to", "is obliged to"),
        permission_cues=("may", "is entitled to", "are entitled to", "is permitted to", "can"),
        prohibition_cues=("shall not", "must not", "may not", "is prohibited", "are prohibited"),
        proposal_cues=("proposes", "is proposed", "would", "seeks to", "intends to"),
        hedge_cues=(
            "approximately",
            "about",
            "around",
            "estimated",
            "is expected to",
            "are expected to",
            "may",
            "could",
            "likely",
            "up to",
            "at least",
            "roughly",
            "in principle",
        ),
        temporal_cues=(
            "from",
            "until",
            "before",
            "after",
            "during",
            "within",
            "as of",
            "with effect from",
            "no later than",
        ),
        duration_units=("day", "days", "week", "weeks", "month", "months", "year", "years"),
        anaphora_openers=(
            "it",
            "they",
            "this",
            "that",
            "these",
            "those",
            "such",
            "the same",
            "he",
            "she",
        ),
        stopwords=frozenset(
            """a an the of to in on for by with from at as is are was were be been being and or
            but if then than that this these those it its their his her which who whom whose
            shall may must not no nor so such into over under between within without per each any
            all both other more most such same own""".split()
        ),
    ),
    "es": LinguisticProfile(
        code="es",
        clause_coordinators=("y", "e", "pero", "mientras", "sin embargo", "aunque", "así como"),
        conditional_cues=(
            "si",
            "salvo que",
            "siempre que",
            "en caso de",
            "cuando",
            "en el evento de",
            "sujeto a",
            "una vez que",
            "a condición de",
        ),
        exception_cues=(
            "salvo",
            "excepto",
            "con excepción de",
            "sin perjuicio de",
            "no se aplica a",
            "no será aplicable a",
            "quedan excluidos",
            "quedan exceptuados",
        ),
        negation_cues=("no", "ni", "nunca", "sin", "tampoco", "ninguno", "ninguna"),
        obligation_cues=(
            "deberá",
            "deberán",
            "debe",
            "deben",
            "estará obligado",
            "estarán obligados",
            "corresponderá",
        ),
        permission_cues=("podrá", "podrán", "puede", "pueden", "tendrá derecho", "tendrán derecho"),
        prohibition_cues=(
            "no podrá",
            "no podrán",
            "queda prohibido",
            "quedan prohibidas",
            "se prohíbe",
        ),
        proposal_cues=("se propone", "propone", "el proyecto", "se plantea", "busca"),
        hedge_cues=(
            "aproximadamente",
            "cerca de",
            "alrededor de",
            "se estima",
            "estimado",
            "se espera",
            "podría",
            "eventualmente",
            "hasta",
            "al menos",
            "en principio",
        ),
        temporal_cues=(
            "desde",
            "hasta",
            "antes de",
            "después de",
            "durante",
            "dentro de",
            "a partir de",
            "a contar de",
            "a más tardar",
        ),
        duration_units=("día", "días", "semana", "semanas", "mes", "meses", "año", "años"),
        anaphora_openers=(
            "éste",
            "este",
            "esta",
            "esto",
            "ello",
            "dicho",
            "dicha",
            "dichos",
            "dichas",
            "el mismo",
            "la misma",
            "aquél",
            "aquella",
        ),
        stopwords=frozenset(
            """el la los las un una unos unas de del al a en y e o u que se su sus por para con
            sin sobre entre desde hasta como más menos este esta estos estas ese esa aquel lo le
            les no ni ser es son era fue han ha haber cuyo cuya cuyos cuyas cuando donde
            respectivamente""".split()
        ),
    ),
    "pt": LinguisticProfile(
        code="pt",
        clause_coordinators=("e", "mas", "enquanto", "no entanto", "embora", "bem como"),
        conditional_cues=("se", "salvo se", "desde que", "caso", "quando", "sujeito a"),
        exception_cues=("salvo", "exceto", "com exceção de", "sem prejuízo de", "não se aplica a"),
        negation_cues=("não", "nem", "nunca", "sem", "nenhum", "nenhuma"),
        obligation_cues=("deverá", "deverão", "deve", "devem", "fica obrigado", "ficam obrigados"),
        permission_cues=("poderá", "poderão", "pode", "podem", "terá direito"),
        prohibition_cues=("não poderá", "não poderão", "é vedado", "fica proibido"),
        proposal_cues=("propõe-se", "propõe", "o projeto", "pretende"),
        hedge_cues=(
            "aproximadamente",
            "cerca de",
            "estima-se",
            "espera-se",
            "poderá",
            "até",
            "pelo menos",
        ),
        temporal_cues=("a partir de", "até", "antes de", "depois de", "durante", "dentro de"),
        duration_units=("dia", "dias", "semana", "semanas", "mês", "meses", "ano", "anos"),
        anaphora_openers=("este", "esta", "isso", "aquele", "referido", "referida", "o mesmo"),
        stopwords=frozenset(
            """o a os as um uma de do da dos das em no na nos nas e ou que se seu sua por para com
            sem sobre entre desde até como mais menos este esta esse essa aquele não nem ser é são
            era foi tem ter quando onde""".split()
        ),
    ),
    "fr": LinguisticProfile(
        code="fr",
        clause_coordinators=("et", "mais", "tandis que", "alors que", "toutefois", "bien que"),
        conditional_cues=(
            "si",
            "sauf si",
            "à condition que",
            "lorsque",
            "dès lors que",
            "sous réserve de",
        ),
        exception_cues=(
            "sauf",
            "excepté",
            "à l'exception de",
            "sans préjudice de",
            "ne s'applique pas à",
        ),
        negation_cues=("ne", "pas", "non", "ni", "jamais", "sans", "aucun", "aucune"),
        obligation_cues=("doit", "doivent", "est tenu de", "sont tenus de", "est obligé"),
        permission_cues=("peut", "peuvent", "a droit", "ont droit", "est autorisé"),
        prohibition_cues=("ne peut", "ne peuvent", "il est interdit", "est interdit"),
        proposal_cues=("propose", "le projet", "vise à"),
        hedge_cues=(
            "environ",
            "approximativement",
            "est estimé",
            "devrait",
            "pourrait",
            "au moins",
        ),
        temporal_cues=("à compter de", "jusqu'à", "avant", "après", "pendant", "dans un délai de"),
        duration_units=(
            "jour",
            "jours",
            "semaine",
            "semaines",
            "mois",
            "an",
            "ans",
            "année",
            "années",
        ),
        anaphora_openers=("il", "elle", "ce", "cette", "ces", "celui-ci", "ledit", "ladite"),
        stopwords=frozenset(
            """le la les un une des du de d au aux à en et ou que qui se sa son ses par pour avec
            sans sur entre depuis jusqu comme plus moins ce cette ces ne pas non est sont était
            été avoir être dont où quand""".split()
        ),
    ),
    "de": LinguisticProfile(
        code="de",
        clause_coordinators=("und", "aber", "während", "jedoch", "obwohl", "sowie"),
        conditional_cues=("wenn", "sofern", "falls", "soweit", "vorausgesetzt", "bei"),
        exception_cues=("außer", "ausgenommen", "mit Ausnahme von", "gilt nicht für"),
        negation_cues=("nicht", "kein", "keine", "nie", "ohne", "weder"),
        obligation_cues=("muss", "müssen", "hat zu", "ist verpflichtet", "sind verpflichtet"),
        permission_cues=("kann", "können", "darf", "dürfen", "ist berechtigt"),
        prohibition_cues=("darf nicht", "dürfen nicht", "ist untersagt", "ist verboten"),
        proposal_cues=("schlägt vor", "der Entwurf", "soll"),
        hedge_cues=(
            "etwa",
            "ungefähr",
            "voraussichtlich",
            "schätzungsweise",
            "mindestens",
            "bis zu",
        ),
        temporal_cues=("ab", "bis", "vor", "nach", "während", "innerhalb von", "spätestens"),
        duration_units=("Tag", "Tage", "Woche", "Wochen", "Monat", "Monate", "Jahr", "Jahre"),
        anaphora_openers=("er", "sie", "es", "dieser", "diese", "dieses", "derselbe", "genannte"),
        stopwords=frozenset(
            """der die das des dem den ein eine eines einem einen und oder aber von zu in im am
            auf für mit ohne über unter zwischen ab bis als wie ist sind war waren sein haben
            nicht kein diese dieser jenes wenn dass""".split()
        ),
    ),
    "it": LinguisticProfile(
        code="it",
        clause_coordinators=("e", "ma", "mentre", "tuttavia", "sebbene", "nonché"),
        conditional_cues=("se", "salvo che", "a condizione che", "qualora", "quando"),
        exception_cues=("salvo", "eccetto", "ad eccezione di", "fatto salvo", "non si applica a"),
        negation_cues=("non", "né", "mai", "senza", "nessun", "nessuna"),
        obligation_cues=("deve", "devono", "è tenuto a", "sono tenuti a"),
        permission_cues=("può", "possono", "ha diritto", "hanno diritto"),
        prohibition_cues=("non può", "non possono", "è vietato", "è fatto divieto"),
        proposal_cues=("propone", "il progetto", "si propone"),
        hedge_cues=("circa", "approssimativamente", "si stima", "dovrebbe", "almeno", "fino a"),
        temporal_cues=("a decorrere da", "fino a", "prima di", "dopo", "durante", "entro"),
        duration_units=(
            "giorno",
            "giorni",
            "settimana",
            "settimane",
            "mese",
            "mesi",
            "anno",
            "anni",
        ),
        anaphora_openers=("esso", "essa", "questo", "questa", "tale", "il medesimo", "predetto"),
        stopwords=frozenset(
            """il lo la i gli le un uno una di del della dei delle a al alla in nel nella e o che
            se si suo sua per con senza su tra fra da come più meno questo questa quello non né è
            sono era stato avere essere quando dove""".split()
        ),
    ),
}


def profile_for_language(tag: str | None) -> LinguisticProfile:
    """Return the profile for a BCP-47 tag, or the neutral fallback.

    Only the primary subtag is consulted: ``es-CL`` and ``es-419`` are the same
    language for the purpose of finding where a clause ends, and encoding
    regional variants would be the first step towards jurisdiction-specific
    behaviour in library code.
    """
    if not tag:
        return GENERIC_PROFILE
    primary = re.split(r"[-_]", tag.strip())[0].lower()
    return LANGUAGE_PROFILES.get(primary, GENERIC_PROFILE)


def profile_for_text(text: str, declared: str | None = None) -> LinguisticProfile:
    """Pick a profile for a body of text, preferring the declared language.

    When the declared tag has no profile — which is the common case for the long
    tail of languages — the text is scored against each profile's function-word
    set. Function words are the right signal precisely because they are the words
    a document cannot avoid regardless of what it is about; scoring on content
    words would make detection depend on subject matter.

    Falls back to :data:`GENERIC_PROFILE` when no profile clears a modest
    threshold, because a wrong profile is worse than none.
    """
    declared_profile = profile_for_language(declared)
    if declared_profile is not GENERIC_PROFILE:
        return declared_profile

    tokens = [t for t in _WORD_RE.findall(text.lower())[:4000] if t]
    if len(tokens) < 20:
        return GENERIC_PROFILE
    best: LinguisticProfile = GENERIC_PROFILE
    best_score = 0.0
    for code in sorted(LANGUAGE_PROFILES):
        profile = LANGUAGE_PROFILES[code]
        hits = sum(1 for token in tokens if token in profile.stopwords)
        score = hits / len(tokens)
        if score > best_score:
            best, best_score = profile, score
    return best if best_score >= 0.12 else GENERIC_PROFILE


# ---------------------------------------------------------------------------
# Text segmentation
#
# Everything here works in character offsets over one source string so that a
# proposition's span is a slice of that string by construction. Reconstructing a
# quote by re-joining tokens is how "verbatim" quietly stops being verbatim.
# ---------------------------------------------------------------------------

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[^\W\d_]+", re.UNICODE)

_PARAGRAPH_RE: Final[re.Pattern[str]] = re.compile(r"\n\s*\n")

_ENUMERATOR_RE: Final[re.Pattern[str]] = re.compile(
    r"(?m)^[ \t]*(?:\(?[a-zA-Z]\)|\(?[ivxlcdmIVXLCDM]{1,6}\)|\d{1,3}[.)]|[-–•·])\s+"
)

_SENTENCE_END_RE: Final[re.Pattern[str]] = re.compile(r"[.!?…¡¿]+")

_SEMICOLON_RE: Final[re.Pattern[str]] = re.compile(r"[;:]")

#: Trailing tokens that make a full stop an abbreviation rather than a sentence
#: end. Deliberately generic across Latin-script legal prose.
_ABBREV_TAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:\b(?:art|arts|inc|no|nos|nro|num|par|pars|cap|lit|fig|tab|vol|ed|pp|p|cf|vs|etc|"
    r"sr|sra|dr|dra|mr|mrs|ms|prof|ing|abs|nr|bzw|ggf|vgl|z|u|s|art\.\s*n)\.?)\s*$",
    re.IGNORECASE,
)

_IDENTIFIER_CUE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:n[º°o]\.?|nr\.?|no\.|#|art\.?|§|artículo|article|artikel|articolo)\s*$",
    re.IGNORECASE,
)

_NUMBER_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<!\w)"
    r"(\d{1,3}(?:[.,\u0020\u00a0\u202f]\d{3})+(?:[.,]\d{1,6})?|\d+(?:[.,]\d{1,6})?)"
    r"(?!\w)"
)

_PERCENT_RE: Final[re.Pattern[str]] = re.compile(
    r"\s*(?:%|percent|por ciento|per cento|pour cent|prozent)", re.IGNORECASE
)
_PERCENT_POINT_RE: Final[re.Pattern[str]] = re.compile(
    r"\s*(?:pp\b|percentage points?|puntos? porcentuales?|punti percentuali)", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class TextUnit:
    """One candidate statement, located by offset in the string it came from.

    ``start``/``end`` index the *source string handed to the segmenter*, not the
    document. Absolute document offsets are computed once, at the point a
    :class:`~aleph.core.models.Span` is built, by adding the base offset phase 1
    recorded for the enclosing provision — so an offset is either exactly right
    or explicitly absent, never approximately right.
    """

    start: int
    end: int
    text: str
    depth: int = 0
    """0 = whole sentence, 1 = coordinate clause, 2 = enumerated sub-item."""
    split_by: str | None = None
    """The cue the unit was cut at, kept so an over-eager split is diagnosable."""


def _trim_offsets(source: str, start: int, end: int) -> tuple[int, int]:
    """Shrink a slice until it neither starts nor ends in whitespace/punctuation.

    Offsets rather than ``str.strip`` because the result must remain an exact
    slice of ``source``: this is the operation that keeps "verbatim" true.
    """
    while start < end and (source[start].isspace() or source[start] in "•·-–,;:"):
        start += 1
    while end > start and (source[end - 1].isspace() or source[end - 1] in ",;:–-"):
        end -= 1
    return start, end


def split_sentences(source: str, profile: LinguisticProfile = GENERIC_PROFILE) -> list[TextUnit]:
    """Split a string into sentence-level units, preserving exact offsets.

    A full stop only ends a sentence when it is not inside a number
    (``18.216``), not a known abbreviation, and is followed by whitespace and
    something that can begin a sentence. Legal prose is dense with all three
    counter-examples, and every wrong split produces a fragment that is quoted
    back to a reader as if the document had said it.
    """
    units: list[TextUnit] = []
    for block_start, block_end in _blocks(source):
        cursor = block_start
        for match in _SENTENCE_END_RE.finditer(source, block_start, block_end):
            stop = match.end()
            if not _is_sentence_boundary(source, match.start(), stop, block_end):
                continue
            start, end = _trim_offsets(source, cursor, stop)
            if end - start >= _MIN_UNIT_CHARS:
                units.append(TextUnit(start, end, source[start:end]))
            cursor = stop
        start, end = _trim_offsets(source, cursor, block_end)
        if end - start >= _MIN_UNIT_CHARS:
            units.append(TextUnit(start, end, source[start:end]))
    return units


def _blocks(source: str) -> list[tuple[int, int]]:
    """Split on blank lines and on enumerator markers at line starts.

    Enumerated items ("a) ... b) ...") are separate provisions of a list in
    almost every drafting tradition, and merging them produces a proposition
    that is true of one item and false of the next.
    """
    coarse: list[tuple[int, int]] = []
    cursor = 0
    for match in _PARAGRAPH_RE.finditer(source):
        coarse.append((cursor, match.start()))
        cursor = match.end()
    coarse.append((cursor, len(source)))

    blocks: list[tuple[int, int]] = []
    for start, end in coarse:
        marks = [m.start() for m in _ENUMERATOR_RE.finditer(source, start, end)]
        bounds = [start, *[m for m in marks if m > start], end]
        for lo, hi in zip(bounds, bounds[1:], strict=False):
            lo2, hi2 = _trim_offsets(source, lo, hi)
            if hi2 > lo2:
                blocks.append((lo2, hi2))
    return blocks


def _is_sentence_boundary(source: str, dot_start: int, stop: int, limit: int) -> bool:
    """Whether a run of terminators genuinely ends a sentence."""
    char = source[dot_start]
    if char == ".":
        before = source[:dot_start]
        after = source[stop:limit]
        if before and before[-1].isdigit() and after[:1].isdigit():
            return False  # 18.216 — a numeral, not a full stop
        if _ABBREV_TAIL_RE.search(before[-14:]):
            return False
        if len(before) >= 2 and before[-1].isupper() and not before[-2].isalpha():
            return False  # single-letter initial
    tail = source[stop:limit]
    if not tail.strip():
        return True
    stripped = tail.lstrip()
    if len(tail) == len(stripped):
        return False  # no whitespace after the terminator
    return stripped[0].isupper() or stripped[0].isdigit() or stripped[0] in "\"'«“(["


@lru_cache(maxsize=256)
def _cue_regex(cues: tuple[str, ...]) -> re.Pattern[str] | None:
    """Compile a word-boundary alternation over a cue set, longest first."""
    if not cues:
        return None
    ordered = sorted({c.strip() for c in cues if c.strip()}, key=len, reverse=True)
    if not ordered:
        return None
    body = "|".join(re.escape(c) for c in ordered)
    return re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.IGNORECASE)


def _token_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _split_clauses(source: str, unit: TextUnit, profile: LinguisticProfile) -> list[TextUnit]:
    """Cut a sentence at coordinators and semicolons that join real statements.

    A coordinator is only a split point when both sides could stand alone: a
    conjunction inside a noun phrase ("goods and services") joins two nouns, and
    splitting there manufactures two propositions the document never made. The
    test is deliberately conservative — under-splitting is recorded honestly as
    ``is_atomic=False``, while over-splitting silently fabricates.
    """
    candidates: list[tuple[int, int, str]] = []
    for match in _SEMICOLON_RE.finditer(source, unit.start, unit.end):
        candidates.append((match.start(), match.end(), source[match.start() : match.end()]))
    coordinator_re = _cue_regex(profile.clause_coordinators)
    if coordinator_re is not None:
        for match in coordinator_re.finditer(source, unit.start, unit.end):
            candidates.append((match.start(), match.end(), match.group(0)))

    parts: list[TextUnit] = []
    cursor = unit.start
    last_cue: str | None = None
    for cut_start, cut_end, cue in sorted(candidates):
        if cut_start <= cursor:
            continue
        left = source[cursor:cut_start]
        right = source[cut_end : unit.end]
        if _token_count(left) < _MIN_CLAUSE_TOKENS or _token_count(right) < _MIN_CLAUSE_TOKENS:
            continue
        start, end = _trim_offsets(source, cursor, cut_start)
        if end - start >= _MIN_UNIT_CHARS:
            parts.append(TextUnit(start, end, source[start:end], depth=1, split_by=last_cue))
            cursor = cut_end
            last_cue = cue
    start, end = _trim_offsets(source, cursor, unit.end)
    if end - start >= _MIN_UNIT_CHARS:
        parts.append(
            TextUnit(start, end, source[start:end], depth=1 if parts else 0, split_by=last_cue)
        )
    return parts or [unit]


def segment_units(source: str, profile: LinguisticProfile = GENERIC_PROFILE) -> list[TextUnit]:
    """Segment a source string into atomic candidate statements.

    Paragraph → enumerated item → sentence → coordinate clause. Returns units in
    document order with exact offsets into ``source``.
    """
    units: list[TextUnit] = []
    for sentence in split_sentences(source, profile):
        units.extend(_split_clauses(source, sentence, profile))
    return units


def locate_verbatim(source: str, quote: str) -> tuple[int, int] | None:
    """Find ``quote`` in ``source``, tolerating only whitespace differences.

    This is the grounding gate for model-produced candidates. An exact match is
    tried first; failing that, the quote's non-whitespace tokens are matched with
    flexible whitespace, which recovers quotes broken by a line wrap in the PDF
    without accepting a paraphrase. Anything looser would defeat the purpose:
    "close to what the document said" is exactly the failure the span exists to
    make impossible.

    Returns:
        ``(start, end)`` offsets into ``source``, or ``None`` when the quote is
        not present — in which case the candidate must be discarded.
    """
    needle = quote.strip()
    if not needle:
        return None
    index = source.find(needle)
    if index >= 0:
        return index, index + len(needle)
    tokens = needle.split()
    if not tokens:
        return None
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    match = re.search(pattern, source)
    if match is None:
        return None
    return match.start(), match.end()


def parse_number(raw: str) -> float | None:
    """Parse a numeral written with either decimal convention.

    Documents from different drafting traditions write ``1.234,56`` and
    ``1,234.56`` for the same quantity, and a pipeline that assumes one
    convention silently reports a thousandfold error. Where the string is
    genuinely ambiguous (``1.234``) the grouping reading is taken and the
    verbatim text is preserved on the :class:`~aleph.core.models.Quantity`, so a
    reader can see what was actually written.
    """
    text = raw.strip()
    for separator in ("\u0020", "\u00a0", "\u202f", "\u2009", "'", "\u2019"):
        text = text.replace(separator, "")
    if not text:
        return None
    has_dot, has_comma = "." in text, "," in text
    if has_dot and has_comma:
        decimal = "." if text.rfind(".") > text.rfind(",") else ","
        grouping = "," if decimal == "." else "."
        text = text.replace(grouping, "").replace(decimal, ".")
    elif has_comma:
        parts = text.split(",")
        if len(parts) > 2 or len(parts[1]) == 3:
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    elif has_dot:
        parts = text.split(".")
        if len(parts) > 2 or len(parts[1]) == 3:
            text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _extract_quantities(source: str, unit: TextUnit, profile: LinguisticProfile) -> list[Quantity]:
    """Pull numeric values out of one unit, keeping the source text verbatim.

    Numerals that look like identifiers (preceded by a numbering cue, or joined
    to another numeral by a hyphen or slash) are skipped. A file number is not a
    quantity, and treating it as one would put a fictitious magnitude into a
    proposition that later gets checked arithmetically.
    """
    out: list[Quantity] = []
    duration_re = _cue_regex(profile.duration_units)
    for match in _NUMBER_RE.finditer(source, unit.start, unit.end):
        raw = match.group(0)
        before = source[max(unit.start, match.start() - 16) : match.start()]
        after = source[match.end() : min(unit.end, match.end() + 24)]
        if _IDENTIFIER_CUE_RE.search(before):
            continue
        if re.match(r"^[-/–]\d", after):
            continue
        value = parse_number(raw)
        if value is None:
            continue

        kind = QuantityKind.COUNT
        unit_label: str | None = None
        suffix = ""
        point_match = _PERCENT_POINT_RE.match(after)
        percent_match = _PERCENT_RE.match(after)
        duration_match = duration_re.match(after.lstrip()) if duration_re is not None else None
        if point_match is not None:
            kind, suffix = QuantityKind.PERCENTAGE_POINT, point_match.group(0)
        elif percent_match is not None:
            kind, suffix = QuantityKind.PERCENTAGE, percent_match.group(0)
        elif duration_match is not None:
            kind = QuantityKind.DURATION
            unit_label = duration_match.group(0)
        elif value.is_integer() and 1800 <= value <= 2200 and re.fullmatch(r"\d{4}", raw):
            # A bare four-digit numeral in this range is almost always a calendar
            # year. Recording it as a count would put a magnitude of two thousand
            # into a proposition that a later arithmetic check would try to verify.
            kind, unit_label = QuantityKind.OTHER, "calendar_year"
        elif not value.is_integer():
            kind = QuantityKind.RATIO

        out.append(Quantity(value=value, kind=kind, unit=unit_label, raw_text=f"{raw}{suffix}"))
    return out


# ---------------------------------------------------------------------------
# Provider interface
#
# Named rather than imported concretely so that this module has no import-time
# dependency on the llm package: a missing or half-written provider must not
# stop phase 2 from running, because phase 2 is not supposed to need one.
# ---------------------------------------------------------------------------


@runtime_checkable
class CompletionProvider(Protocol):
    """The single method phase 2 needs from a language model.

    Mirrors :class:`aleph.llm.base.LLMProvider`. Structural rather than nominal
    typing is used on purpose: the grounding gate below means a provider cannot
    influence what Aleph publishes except by pointing at text that is already in
    the document, so there is nothing to be gained by demanding a particular
    base class — and a hard import would make the deterministic path depend on
    the optional one.
    """

    def complete(
        self, prompt: str, *, schema: Mapping[str, Any] | None = None
    ) -> str | dict[str, Any] | list[Any]:
        """Return a completion, parsed as JSON when ``schema`` is supplied."""
        ...


#: JSON Schema handed to a provider that supports structured output. It permits
#: only fields whose content can be verified against the source text; there is
#: deliberately no confidence field, because a model's opinion of its own output
#: is not evidence and would compete with the extraction confidence computed here.
LLM_PROPOSITION_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "propositions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "quote": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Verbatim substring of the passage. Copy exactly.",
                    },
                    "proposition_type": {
                        "type": "string",
                        "enum": [t.value for t in PropositionType],
                    },
                    "modality": {
                        "type": ["string", "null"],
                        "enum": [*[m.value for m in Modality], None],
                    },
                    "subject": {"type": ["string", "null"]},
                    "predicate_summary": {"type": ["string", "null"]},
                    "object": {"type": ["string", "null"]},
                    "is_negated": {"type": "boolean"},
                    "negation_cue": {"type": ["string", "null"]},
                    "conditions": {"type": "array", "items": {"type": "string"}},
                    "exceptions": {"type": "array", "items": {"type": "string"}},
                    "temporal": {"type": ["string", "null"]},
                    "population": {"type": ["string", "null"]},
                    "geographic": {"type": ["string", "null"]},
                    "hedges": {"type": "array", "items": {"type": "string"}},
                    "is_atomic": {"type": "boolean"},
                    "is_self_contained": {"type": "boolean"},
                },
                "required": ["text", "quote", "proposition_type"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["propositions"],
    "additionalProperties": False,
}


_PROMPT_TEMPLATE: Final[str] = """\
You are decomposing one passage of a policy document into atomic propositions.

RULES
1. Each proposition asserts exactly ONE thing: one subject, one predicate. Split
   coordinated statements; never join two.
2. Each proposition must be self-contained: replace pronouns with the entity
   they refer to, using only wording present in the passage.
3. `quote` MUST be an exact, contiguous, character-for-character substring of the
   passage below. Do not paraphrase, correct, translate or reformat it. A
   proposition whose quote is not found in the passage will be discarded.
4. Preserve negation, conditions and exceptions as separate fields, not inside
   the text.
5. Record only what the passage says. Do not add background, consequences or
   evaluation.
6. Reply with JSON only, matching the requested schema.

PASSAGE LANGUAGE: {language}
PASSAGE:
\"\"\"
{passage}
\"\"\"
"""


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Cursor:
    """Deterministic proposition numbering for one document.

    Ids are sequential in traversal order rather than content-hashed so that a
    reader can see two propositions came from the same part of the document, and
    so a bundle diffs readably when a document is re-analysed.
    """

    slug: str
    count: int = 0

    def next_id(self) -> str:
        self.count += 1
        return proposition_id(self.slug, self.count)


@dataclass(slots=True)
class _Rejection:
    """A candidate that failed the grounding gate, kept for the run's notes."""

    reason: str
    detail: str


class PropositionExtractor(ABC):
    """Common interface for phase 2 implementations.

    Both implementations must satisfy the same contract: every returned
    proposition carries a span whose text is a verbatim substring of the source
    document. That invariant is what makes the two paths interchangeable — a
    consumer never has to know which one ran to know what a span means.
    """

    #: Short, stable name recorded in ``PropositionSet.extractor``.
    name: str = "extractor"

    @abstractmethod
    def extract(
        self,
        document: DocumentModel,
        *,
        generated_at: str | None = None,
    ) -> PropositionSet:
        """Decompose ``document`` into atomic propositions."""

    def _extractor_tag(self) -> str:
        return f"aleph.propositions.extract.{self.name}@{EXTRACTOR_VERSION}"


class RuleBasedExtractor(PropositionExtractor):
    """Deterministic extraction with no model, no network and no credentials.

    This is the floor of the system, and it is a real floor rather than a
    placeholder: it segments provisions into clauses, anchors propositions on the
    quantities and money phase 1 already resolved, detects conditionality,
    negation, modality, temporal scope and exceptions from function-word cues,
    and turns definitions, assumptions and deadlines into their own typed
    propositions.

    Its output is intentionally conservative. Where the segmenter cannot show
    that a conjunction joins two statements it leaves them joined and reports
    ``is_atomic=False``; where a clause opens with an unresolved pronoun it
    reports ``is_self_contained=False`` instead of guessing a referent. Both
    flags are read downstream to keep such propositions out of single-verdict
    evaluation, so the honest answer costs nothing and the guess would cost a
    wrong verdict.
    """

    name = "RuleBasedExtractor"

    def __init__(self, *, profile: LinguisticProfile | None = None) -> None:
        self._forced_profile = profile

    # -- public API --------------------------------------------------------

    def extract(
        self,
        document: DocumentModel,
        *,
        generated_at: str | None = None,
    ) -> PropositionSet:
        profile = self._profile_for(document)
        cursor = _Cursor(slug=document.identity.slug)
        propositions: list[Proposition] = []
        covered: set[str] = set()

        for provision in sorted(document.provisions, key=lambda p: p.id):
            produced = self.extract_from_provision(document, provision, cursor, profile=profile)
            if produced:
                covered.add(provision.id)
            propositions.extend(produced)

        propositions.extend(self._definition_propositions(document, cursor, profile))
        propositions.extend(self._assumption_propositions(document, cursor, profile))
        propositions.extend(self._deadline_propositions(document, cursor, profile))

        return self._assemble(document, propositions, covered, generated_at, profile)

    def extract_from_provision(
        self,
        document: DocumentModel,
        provision: Provision,
        cursor: _Cursor,
        *,
        profile: LinguisticProfile | None = None,
    ) -> list[Proposition]:
        """Decompose a single provision. Exposed so the LLM path can fall back.

        Returns propositions in document order; the caller owns numbering via
        ``cursor``, which keeps ids sequential across a mixed run.
        """
        profile = profile or self._profile_for(document)
        source, base_offset = _provision_source(provision)
        if not source.strip():
            return []

        units = segment_units(source, profile)
        out: list[Proposition] = []
        clause_ids: list[str] = []
        for unit in units:
            proposition = self._proposition_from_unit(
                document, provision, unit, source, base_offset, cursor, profile
            )
            if proposition is not None:
                out.append(proposition)
                clause_ids.append(proposition.id)

        out.extend(self._value_propositions(document, provision, cursor, profile, clause_ids))
        return out

    # -- unit → proposition -------------------------------------------------

    def _proposition_from_unit(
        self,
        document: DocumentModel,
        provision: Provision,
        unit: TextUnit,
        source: str,
        base_offset: int | None,
        cursor: _Cursor,
        profile: LinguisticProfile,
    ) -> Proposition | None:
        verbatim = source[unit.start : unit.end]
        if not verbatim.strip() or _token_count(verbatim) < 3:
            return None

        negation = _detect_negation(verbatim, profile)
        modality = _detect_modality(verbatim, profile, provision)
        conditions = _detect_conditions(verbatim, profile)
        exceptions = sorted({*_detect_exceptions(verbatim, profile), *provision.exceptions})
        temporal = _detect_temporal(verbatim, profile) or provision.effective_condition
        hedges = _detect_hedges(verbatim, profile)
        quantities = _extract_quantities(source, unit, profile)
        prop_type = _classify(verbatim, provision, conditions, quantities, profile)

        anaphoric = _opens_with_anaphora(verbatim, profile)
        normalised = _normalise_whitespace(verbatim)
        self_contained = not anaphoric
        if anaphoric and provision.title:
            normalised = f"{provision.title}: {normalised}"
            self_contained = True

        atomic = unit.depth > 0 or not _has_residual_coordinator(verbatim, profile)

        scope = PropositionScope(
            temporal=temporal,
            geographic="; ".join(provision.affected_regions) or None,
            population="; ".join(provision.affected_populations) or None,
            conditions=conditions,
            exceptions=exceptions,
        )

        return Proposition(
            id=cursor.next_id(),
            text=normalised,
            proposition_type=prop_type,
            statement_type=_statement_type_for(prop_type, modality),
            subject=provision.title or None,
            predicate_summary=_predicate_summary(normalised),
            object=None,
            quantities=quantities,
            money=[],
            provenance=_grounded(
                document,
                provision,
                verbatim,
                base_offset,
                unit.start,
                unit.end,
                self.name,
            ),
            derived_from_provision_id=provision.id,
            derived_from_section_id=provision.section_id,
            confidence=_extraction_confidence(
                document,
                atomic=atomic,
                self_contained=self_contained,
                has_offsets=base_offset is not None,
                quantified=bool(quantities),
            ),
            negation=negation,
            scope=scope,
            modality=modality,
            hedges=hedges,
            is_atomic=atomic,
            is_self_contained=self_contained,
            tags=_tags_for(provision, prop_type),
        )

    # -- value-anchored propositions ---------------------------------------

    def _value_propositions(
        self,
        document: DocumentModel,
        provision: Provision,
        cursor: _Cursor,
        profile: LinguisticProfile,
        clause_ids: Sequence[str],
    ) -> list[Proposition]:
        """One proposition per figure phase 1 resolved for this provision.

        Figures get their own propositions because they are the part of a
        document that can actually be checked against something outside it, and
        because a figure buried inside a long clause inherits that clause's
        qualifiers when it should carry its own. Each is anchored on the figure's
        own span, so the number and the passage it came from travel together.
        """
        out: list[Proposition] = []
        related = sorted(clause_ids)

        for value in sorted(
            (v for v in document.monetary_values if v.provision_id == provision.id),
            key=lambda v: v.id,
        ):
            text = _normalise_whitespace(value.span.text)
            out.append(
                Proposition(
                    id=cursor.next_id(),
                    text=f"{value.label}: {text}" if value.label else text,
                    proposition_type=PropositionType.QUANTITATIVE,
                    statement_type=(
                        StatementType.FORECAST if value.is_estimate else StatementType.FACT
                    ),
                    subject=value.label or provision.title,
                    predicate_summary=value.role.value,
                    money=[value.money],
                    provenance=_grounded_from_span(document, value.span, self.name),
                    derived_from_provision_id=provision.id,
                    derived_from_section_id=provision.section_id,
                    confidence=_extraction_confidence(
                        document,
                        atomic=True,
                        self_contained=True,
                        has_offsets=value.span.char_start is not None,
                        quantified=True,
                    ),
                    negation=Negation(is_negated=False),
                    scope=PropositionScope(
                        temporal=provision.effective_condition,
                        conditions=list(provision.conditions),
                        exceptions=list(provision.exceptions),
                    ),
                    modality=Modality.PROPOSED if value.is_estimate else Modality.ASSERTED,
                    hedges=_detect_hedges(value.span.text, profile),
                    related_proposition_ids=related,
                    tags=["monetary", value.role.value],
                )
            )

        for mention in sorted(
            (q for q in document.quantities if q.provision_id == provision.id),
            key=lambda q: q.id,
        ):
            text = _normalise_whitespace(mention.span.text)
            out.append(
                Proposition(
                    id=cursor.next_id(),
                    text=f"{mention.label}: {text}" if mention.label else text,
                    proposition_type=PropositionType.QUANTITATIVE,
                    statement_type=StatementType.FACT,
                    subject=mention.label or provision.title,
                    predicate_summary=mention.role.value if mention.role else None,
                    quantities=[mention.quantity],
                    provenance=_grounded_from_span(document, mention.span, self.name),
                    derived_from_provision_id=provision.id,
                    derived_from_section_id=provision.section_id,
                    confidence=_extraction_confidence(
                        document,
                        atomic=True,
                        self_contained=True,
                        has_offsets=mention.span.char_start is not None,
                        quantified=True,
                    ),
                    negation=Negation(is_negated=False),
                    scope=PropositionScope(conditions=list(provision.conditions)),
                    modality=Modality.ASSERTED,
                    related_proposition_ids=related,
                    tags=["quantitative"],
                )
            )
        return out

    # -- document-level propositions ---------------------------------------

    def _definition_propositions(
        self, document: DocumentModel, cursor: _Cursor, profile: LinguisticProfile
    ) -> list[Proposition]:
        """A document's private definitions, as propositions true by stipulation.

        These are separated because they are not empirical claims at all: a
        document that defines 'small enterprise' has not asserted anything about
        the world, and grading such a statement true or false is a category
        error. They matter enormously anyway — most disputes about what an
        instrument does turn on a word it defined for itself.
        """
        out: list[Proposition] = []
        for definition in sorted(document.definitions, key=lambda d: d.id):
            text = _normalise_whitespace(definition.definition_text)
            out.append(
                Proposition(
                    id=cursor.next_id(),
                    text=f"'{definition.term}' means {text}",
                    proposition_type=PropositionType.DEFINITIONAL,
                    statement_type=StatementType.INTERPRETATION,
                    subject=definition.term,
                    predicate_summary="is defined as",
                    provenance=_grounded_from_span(document, definition.span, self.name),
                    derived_from_provision_id=(
                        definition.provision_id
                        if definition.provision_id and definition.provision_id.startswith("prov:")
                        else None
                    ),
                    confidence=_extraction_confidence(
                        document,
                        atomic=True,
                        self_contained=True,
                        has_offsets=definition.span.char_start is not None,
                        quantified=False,
                    ),
                    negation=Negation(is_negated=False),
                    scope=PropositionScope(population=definition.scope),
                    modality=Modality.ASSERTED,
                    hedges=_detect_hedges(definition.definition_text, profile),
                    tags=["definition"],
                )
            )
        return out

    def _assumption_propositions(
        self, document: DocumentModel, cursor: _Cursor, profile: LinguisticProfile
    ) -> list[Proposition]:
        """The inputs a document's own projections rest on.

        Extracted as propositions in their own right because a forecast is only
        evaluable against its assumptions. If an instrument assumed a growth path
        that did not materialise, its projection was not thereby dishonest — and
        Aleph can only say so if the assumption is on the record as a separate,
        quotable statement.
        """
        out: list[Proposition] = []
        for assumption in sorted(document.assumptions, key=lambda a: a.id):
            out.append(
                Proposition(
                    id=cursor.next_id(),
                    text=_normalise_whitespace(assumption.statement),
                    proposition_type=PropositionType.ASSUMPTION,
                    statement_type=StatementType.FORECAST,
                    subject=assumption.stated_by,
                    predicate_summary=assumption.assumption_type.value,
                    quantities=(
                        [assumption.quantified_value] if assumption.quantified_value else []
                    ),
                    money=[assumption.quantified_money] if assumption.quantified_money else [],
                    provenance=_grounded_from_span(document, assumption.span, self.name),
                    confidence=_extraction_confidence(
                        document,
                        atomic=True,
                        self_contained=assumption.is_explicit,
                        has_offsets=assumption.span.char_start is not None,
                        quantified=bool(assumption.quantified_money or assumption.quantified_value),
                    ),
                    negation=Negation(is_negated=False),
                    scope=PropositionScope(),
                    modality=Modality.HYPOTHETICAL,
                    hedges=_detect_hedges(assumption.statement, profile),
                    is_self_contained=assumption.is_explicit,
                    tags=["assumption", assumption.assumption_type.value]
                    + ([] if assumption.is_explicit else ["inferred_assumption"]),
                )
            )
        return out

    def _deadline_propositions(
        self, document: DocumentModel, cursor: _Cursor, profile: LinguisticProfile
    ) -> list[Proposition]:
        """Time-bound obligations, which are what make implementation checkable."""
        out: list[Proposition] = []
        for deadline in sorted(document.deadlines, key=lambda d: d.id):
            when = deadline.date or deadline.relative_period or deadline.trigger
            out.append(
                Proposition(
                    id=cursor.next_id(),
                    text=_normalise_whitespace(
                        f"{deadline.label}{f' — due {when}' if when else ''}"
                    ),
                    proposition_type=PropositionType.TEMPORAL,
                    statement_type=StatementType.FACT,
                    subject=deadline.obligated_party,
                    predicate_summary="must act by",
                    provenance=_grounded_from_span(document, deadline.span, self.name),
                    derived_from_provision_id=(
                        deadline.provision_id
                        if deadline.provision_id and deadline.provision_id.startswith("prov:")
                        else None
                    ),
                    confidence=_extraction_confidence(
                        document,
                        atomic=True,
                        self_contained=bool(deadline.obligated_party),
                        has_offsets=deadline.span.char_start is not None,
                        quantified=False,
                    ),
                    negation=Negation(is_negated=False),
                    scope=PropositionScope(
                        temporal=when,
                        conditions=[deadline.trigger] if deadline.trigger else [],
                    ),
                    modality=Modality.OBLIGATORY,
                    hedges=_detect_hedges(deadline.span.text, profile),
                    is_self_contained=bool(deadline.obligated_party),
                    tags=["deadline"],
                )
            )
        return out

    # -- helpers -----------------------------------------------------------

    def _profile_for(self, document: DocumentModel) -> LinguisticProfile:
        if self._forced_profile is not None:
            return self._forced_profile
        sample = "\n".join(p.text for p in document.provisions[:40]) or document.identity.title
        return profile_for_text(sample, document.identity.language)

    def _assemble(
        self,
        document: DocumentModel,
        propositions: Sequence[Proposition],
        covered: set[str],
        generated_at: str | None,
        profile: LinguisticProfile,
        notes: str | None = None,
    ) -> PropositionSet:
        skipped = sorted(
            {
                p.section_id
                for p in document.provisions
                if p.id not in covered and p.section_id is not None
            }
        )
        coverage = PropositionCoverage(
            provisions_total=len(document.provisions),
            provisions_with_propositions=len(covered),
            sections_not_processed=skipped,
            note=(
                "Provisions with no extracted proposition yielded no segment long enough "
                "to stand as a statement; their text is still available in the document model."
                if len(covered) < len(document.provisions)
                else None
            ),
        )
        base_note = (
            f"Segmentation profile: {profile.code}. "
            "Every proposition carries a verbatim span; candidates that could not be "
            "located in the source text were discarded rather than published."
        )
        return PropositionSet(
            schema_version=SCHEMA_VERSION,
            data_status=document.data_status or DataStatus.DERIVED,
            document_id=document.id,
            generated_at=generated_at,
            extractor=self._extractor_tag(),
            propositions=sorted(propositions, key=lambda p: p.id),
            coverage=coverage,
            notes=f"{base_note} {notes}".strip() if notes else base_note,
        )


class LLMPropositionExtractor(PropositionExtractor):
    """Model-assisted extraction, gated by the same verbatim-span requirement.

    A language model is good at the one thing rules are bad at: recognising that
    a long subordinate clause carries a second assertion, and restating it
    without its pronouns. It is also good at producing fluent text that the
    document does not contain. This class takes the first and structurally
    refuses the second — every candidate must supply a ``quote`` that is found in
    the passage by :func:`locate_verbatim`, and candidates that fail are counted
    and discarded.

    The model therefore cannot introduce content: it can only point at text that
    is already there and say how to split it. Where it returns nothing usable for
    a provision, the rule-based extractor runs on that provision instead, so the
    result is never worse than the deterministic path. Provider failures are the
    same case — caught, recorded, fallen back from — because an analysis that
    disappears when an endpoint is down publishes silence that reads as an
    absence of content.
    """

    name = "LLMPropositionExtractor"

    def __init__(
        self,
        provider: CompletionProvider,
        *,
        fallback: RuleBasedExtractor | None = None,
        profile: LinguisticProfile | None = None,
        strict: bool = False,
        max_candidates_per_provision: int = 40,
    ) -> None:
        self._provider = provider
        self._fallback = fallback or RuleBasedExtractor(profile=profile)
        self._forced_profile = profile
        self._strict = strict
        """When True a provider error propagates instead of falling back. Off by
        default: the deterministic path is always a correct answer."""
        self._max_candidates = max_candidates_per_provision

    @property
    def provider_name(self) -> str:
        return str(getattr(self._provider, "name", type(self._provider).__name__))

    def _extractor_tag(self) -> str:
        return f"aleph.propositions.extract.{self.name}[{self.provider_name}]@{EXTRACTOR_VERSION}"

    def extract(
        self,
        document: DocumentModel,
        *,
        generated_at: str | None = None,
    ) -> PropositionSet:
        profile = self._forced_profile or self._fallback._profile_for(document)
        cursor = _Cursor(slug=document.identity.slug)
        propositions: list[Proposition] = []
        covered: set[str] = set()
        rejections: list[_Rejection] = []
        fell_back: list[str] = []

        for provision in sorted(document.provisions, key=lambda p: p.id):
            produced = self._from_provision(document, provision, cursor, profile, rejections)
            if not produced:
                produced = self._fallback.extract_from_provision(
                    document, provision, cursor, profile=profile
                )
                if produced:
                    fell_back.append(provision.id)
            if produced:
                covered.add(provision.id)
            propositions.extend(produced)

        # Definitions, assumptions and deadlines are already structured by phase
        # 1; passing them through a model could only lose the structure.
        propositions.extend(self._fallback._definition_propositions(document, cursor, profile))
        propositions.extend(self._fallback._assumption_propositions(document, cursor, profile))
        propositions.extend(self._fallback._deadline_propositions(document, cursor, profile))

        notes_parts: list[str] = []
        if rejections:
            notes_parts.append(
                f"{len(rejections)} model candidate(s) discarded for failing the "
                "verbatim-span check."
            )
        if fell_back:
            notes_parts.append(f"{len(fell_back)} provision(s) fell back to rule-based extraction.")
        result = self._fallback._assemble(
            document,
            propositions,
            covered,
            generated_at,
            profile,
            notes=" ".join(notes_parts) or None,
        )
        return result.model_copy(update={"extractor": self._extractor_tag()})

    # -- provider round trip ------------------------------------------------

    def _from_provision(
        self,
        document: DocumentModel,
        provision: Provision,
        cursor: _Cursor,
        profile: LinguisticProfile,
        rejections: list[_Rejection],
    ) -> list[Proposition]:
        source, base_offset = _provision_source(provision)
        if not source.strip():
            return []

        prompt = _PROMPT_TEMPLATE.format(
            language=document.identity.language or "unspecified", passage=source
        )
        try:
            raw = self._provider.complete(prompt, schema=LLM_PROPOSITION_SCHEMA)
        except Exception as exc:  # noqa: BLE001 - provider failures are expected
            if self._strict:
                raise ProviderError(
                    "proposition extraction provider failed",
                    provider=self.provider_name,
                    operation="complete",
                    retryable=True,
                    detail=str(exc)[:400],
                ) from exc
            rejections.append(_Rejection("provider_error", f"{provision.id}: {exc}"[:300]))
            return []

        candidates = _parse_candidates(raw)
        if not candidates:
            rejections.append(_Rejection("empty_response", provision.id))
            return []

        out: list[Proposition] = []
        for candidate in candidates[: self._max_candidates]:
            proposition = self._candidate_to_proposition(
                document, provision, candidate, source, base_offset, cursor, profile, rejections
            )
            if proposition is not None:
                out.append(proposition)
        return out

    def _candidate_to_proposition(
        self,
        document: DocumentModel,
        provision: Provision,
        candidate: Mapping[str, Any],
        source: str,
        base_offset: int | None,
        cursor: _Cursor,
        profile: LinguisticProfile,
        rejections: list[_Rejection],
    ) -> Proposition | None:
        text = str(candidate.get("text") or "").strip()
        quote = str(candidate.get("quote") or "").strip()
        if not text or not quote:
            rejections.append(_Rejection("missing_field", f"{provision.id}: text or quote absent"))
            return None

        located = locate_verbatim(source, quote)
        if located is None:
            # The single most important line in this class. A candidate whose
            # quote is not in the passage is a fabrication, however plausible.
            rejections.append(_Rejection("ungrounded_quote", f"{provision.id}: {quote[:120]}"))
            return None
        start, end = located
        verbatim = source[start:end]

        try:
            prop_type = PropositionType(str(candidate.get("proposition_type")))
        except ValueError:
            prop_type = _classify(verbatim, provision, [], [], profile)
        modality = _coerce_modality(candidate.get("modality")) or _detect_modality(
            verbatim, profile, provision
        )

        conditions = _string_list(candidate.get("conditions"))
        exceptions = sorted({*_string_list(candidate.get("exceptions")), *provision.exceptions})
        quantities = _extract_quantities(source, TextUnit(start, end, verbatim), profile)
        is_negated = bool(candidate.get("is_negated"))
        detected_negation = _detect_negation(verbatim, profile)
        negation = Negation(
            is_negated=is_negated or detected_negation.is_negated,
            negated_element=str(candidate.get("predicate_summary") or "") or None,
            cue_text=(
                str(candidate.get("negation_cue") or "") or detected_negation.cue_text or None
            ),
        )
        atomic = bool(candidate.get("is_atomic", True))
        self_contained = bool(
            candidate.get("is_self_contained", True)
        ) and not _opens_with_anaphora(text, profile)

        return Proposition(
            id=cursor.next_id(),
            text=_normalise_whitespace(text),
            proposition_type=prop_type,
            statement_type=_statement_type_for(prop_type, modality),
            subject=_optional_str(candidate.get("subject")),
            predicate_summary=_optional_str(candidate.get("predicate_summary")),
            object=_optional_str(candidate.get("object")),
            quantities=quantities,
            provenance=_grounded(
                document, provision, verbatim, base_offset, start, end, self.provider_name
            ),
            derived_from_provision_id=provision.id,
            derived_from_section_id=provision.section_id,
            confidence=_extraction_confidence(
                document,
                atomic=atomic,
                self_contained=self_contained,
                has_offsets=base_offset is not None,
                quantified=bool(quantities),
                model_assisted=True,
            ),
            negation=negation,
            scope=PropositionScope(
                temporal=_optional_str(candidate.get("temporal")) or provision.effective_condition,
                geographic=_optional_str(candidate.get("geographic")),
                population=_optional_str(candidate.get("population")),
                conditions=conditions,
                exceptions=exceptions,
            ),
            modality=modality,
            hedges=_string_list(candidate.get("hedges")) or _detect_hedges(verbatim, profile),
            is_atomic=atomic,
            is_self_contained=self_contained,
            tags=_tags_for(provision, prop_type) + ["model_assisted"],
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def extract_propositions(
    document: DocumentModel,
    *,
    provider: CompletionProvider | None = None,
    generated_at: str | None = None,
    profile: LinguisticProfile | None = None,
    strict: bool = False,
) -> PropositionSet:
    """Run warm phase 2 over ``document``.

    With no ``provider`` this is the deterministic rule-based path, which is a
    complete implementation rather than a degraded mode: the pipeline is designed
    to run end to end with no model, so that a result never depends on an
    endpoint being reachable.

    Args:
        document: The phase-1 reading of the source document.
        provider: Optional language-model provider. When supplied, model
            candidates are accepted only if they quote the source verbatim, and
            any provision the model cannot handle falls back to rules.
        generated_at: UTC timestamp to stamp on the set. Left ``None`` by default
            so that two runs over the same document produce byte-identical
            output; the pipeline supplies it when a run is being recorded.
        profile: Override language detection. Rarely needed.
        strict: Propagate provider failures instead of falling back.

    Returns:
        A :class:`~aleph.core.models.PropositionSet` whose every member carries a
        verbatim span.
    """
    extractor: PropositionExtractor
    if provider is None:
        extractor = RuleBasedExtractor(profile=profile)
    else:
        extractor = LLMPropositionExtractor(provider, profile=profile, strict=strict)
    return extractor.extract(document, generated_at=generated_at)


# ---------------------------------------------------------------------------
# Shared detail
# ---------------------------------------------------------------------------


def _provision_source(provision: Provision) -> tuple[str, int | None]:
    """Choose the string to segment, and the document offset it starts at.

    The span text is preferred because phase 1 recorded where it begins, which
    is what lets a proposition's offsets be exactly right. When the provision's
    normalised text is materially longer — a span holding only a heading, say —
    that text is used instead and offsets are dropped rather than guessed. An
    absent offset is honest; a wrong one silently points a reader at the wrong
    passage.
    """
    span_text = provision.span.text or ""
    if span_text.strip() and len(span_text) >= len(provision.text) * 0.8:
        return span_text, provision.span.char_start
    if provision.text.strip():
        return provision.text, None
    return span_text, provision.span.char_start


def _grounded(
    document: DocumentModel,
    provision: Provision,
    verbatim: str,
    base_offset: int | None,
    start: int,
    end: int,
    extractor: str,
) -> GroundedProvenance:
    """Build provenance whose span is a verbatim slice with true offsets."""
    char_start = base_offset + start if base_offset is not None else None
    char_end = base_offset + end if base_offset is not None else None
    return GroundedProvenance(
        source_id=document.id,
        source_kind=ProvenanceSourceKind.DOCUMENT,
        url=document.source.url,
        retrieved_at=document.source.retrieved_at,
        span=Span(
            page=provision.span.page,
            section_id=provision.section_id or provision.span.section_id,
            char_start=char_start,
            char_end=char_end,
            text=verbatim,
        ),
        extractor=f"{extractor}@{EXTRACTOR_VERSION}",
    )


def _grounded_from_span(document: DocumentModel, span: Span, extractor: str) -> GroundedProvenance:
    """Provenance for an item phase 1 already located precisely."""
    return GroundedProvenance(
        source_id=document.id,
        source_kind=ProvenanceSourceKind.DOCUMENT,
        url=document.source.url,
        retrieved_at=document.source.retrieved_at,
        span=span,
        extractor=f"{extractor}@{EXTRACTOR_VERSION}",
    )


def _normalise_whitespace(text: str) -> str:
    """Collapse runs of whitespace for the readable ``text`` field only.

    The verbatim passage in ``provenance.span.text`` is never touched, so any
    drift between the two is visible to a reader who opens the provenance.
    """
    return re.sub(r"\s+", " ", text).strip()


def _predicate_summary(text: str, *, max_words: int = 8) -> str | None:
    words = text.split()
    if len(words) < 2:
        return None
    return " ".join(words[1 : 1 + max_words])


def _optional_str(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Iterable):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _coerce_modality(value: object) -> Modality | None:
    if value is None:
        return None
    try:
        return Modality(str(value))
    except ValueError:
        return None


def _detect_negation(text: str, profile: LinguisticProfile) -> Negation:
    """Record denial as structured data, with the cue quoted from the source.

    Negation is the single most fragile thing in paraphrase and the cheapest way
    to invert a verdict, so the cue is captured verbatim: a reader who doubts the
    reading can see exactly which word produced it.
    """
    pattern = _cue_regex(profile.negation_cues)
    if pattern is None:
        return Negation(is_negated=False)
    match = pattern.search(text)
    if match is None:
        return Negation(is_negated=False)
    return Negation(is_negated=True, cue_text=match.group(0), negated_element=None)


def _detect_modality(text: str, profile: LinguisticProfile, provision: Provision) -> Modality:
    """Distinguish a duty from a discretion from a projection.

    Checked in order of strength: a prohibition cue outranks an obligation cue,
    which outranks a permission cue, because 'may not' contains 'may' and
    reading it as a permission would report a ban as a licence. Where the text
    gives no cue the provision's own type is used, and only then does the neutral
    ``asserted`` apply.
    """
    for cues, modality in (
        (profile.prohibition_cues, Modality.PROHIBITIVE),
        (profile.obligation_cues, Modality.OBLIGATORY),
        (profile.permission_cues, Modality.PERMISSIVE),
        (profile.proposal_cues, Modality.PROPOSED),
    ):
        pattern = _cue_regex(cues)
        if pattern is not None and pattern.search(text):
            return modality
    mapping = {
        ProvisionType.OBLIGATION: Modality.OBLIGATORY,
        ProvisionType.REPORTING_REQUIREMENT: Modality.OBLIGATORY,
        ProvisionType.PROHIBITION: Modality.PROHIBITIVE,
        ProvisionType.PERMISSION: Modality.PERMISSIVE,
        ProvisionType.ENTITLEMENT: Modality.PERMISSIVE,
        ProvisionType.DELEGATION: Modality.PERMISSIVE,
    }
    return mapping.get(provision.provision_type, Modality.ASSERTED)


def _detect_conditions(text: str, profile: LinguisticProfile) -> list[str]:
    """Capture antecedents verbatim, from the cue to the end of the clause.

    Kept verbatim because a conditional proposition asserted unconditionally is a
    different — and stronger — proposition than the document made.
    """
    pattern = _cue_regex(profile.conditional_cues)
    if pattern is None:
        return []
    out: list[str] = []
    for match in pattern.finditer(text):
        tail = text[match.start() :]
        stop = re.search(r"[,;.]", tail[1:])
        clause = tail[: stop.start() + 1] if stop else tail
        cleaned = _normalise_whitespace(clause)
        if len(cleaned) > 3 and cleaned not in out:
            out.append(cleaned)
    return out


def _detect_exceptions(text: str, profile: LinguisticProfile) -> list[str]:
    """Capture carve-outs verbatim. Dropping one is how a true summary turns false."""
    pattern = _cue_regex(profile.exception_cues)
    if pattern is None:
        return []
    out: list[str] = []
    for match in pattern.finditer(text):
        tail = text[match.start() :]
        stop = re.search(r"[;.]", tail[1:])
        clause = tail[: stop.start() + 1] if stop else tail
        cleaned = _normalise_whitespace(clause)
        if len(cleaned) > 3 and cleaned not in out:
            out.append(cleaned)
    return out


def _detect_temporal(text: str, profile: LinguisticProfile) -> str | None:
    """Capture the stated time bound, preferring an explicit date.

    A temporal cue alone is not enough. Several of them ("up to", "hasta",
    "bis zu") do double duty as magnitude qualifiers, and "up to 300 units" is
    not a deadline. The captured clause must therefore also contain something
    time-shaped — an ISO date, a four-digit year, or a duration unit — before it
    is recorded as scope. A false temporal bound would make a proposition look
    narrower than the document made it, which is the same class of error as
    dropping one.
    """
    iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if iso:
        return iso.group(0)
    pattern = _cue_regex(profile.temporal_cues)
    if pattern is None:
        return None
    duration_re = _cue_regex(profile.duration_units)
    for match in pattern.finditer(text):
        tail = text[match.start() :]
        stop = re.search(r"[,;.]", tail[1:])
        clause = tail[: stop.start() + 1] if stop else tail
        cleaned = _normalise_whitespace(clause)
        if len(cleaned) <= 3:
            continue
        has_year = re.search(r"\b(1[89]\d{2}|2[01]\d{2})\b", cleaned) is not None
        has_duration = duration_re is not None and duration_re.search(cleaned) is not None
        if has_year or has_duration:
            return cleaned
    return None


def _detect_hedges(text: str, profile: LinguisticProfile) -> list[str]:
    """Collect hedging expressions verbatim.

    Preserved because stripping a hedge inflates certainty, and certainty
    inflation is one of the eight framing dimensions Aleph measures elsewhere. A
    pipeline that quietly removed 'approximately' would be committing the fault
    it reports.
    """
    pattern = _cue_regex(profile.hedge_cues)
    if pattern is None:
        return []
    seen: list[str] = []
    for match in pattern.finditer(text):
        cue = match.group(0)
        if cue.lower() not in {s.lower() for s in seen}:
            seen.append(cue)
    return seen


def _opens_with_anaphora(text: str, profile: LinguisticProfile) -> bool:
    """Whether a fragment starts with a reference to something outside itself."""
    pattern = _cue_regex(profile.anaphora_openers)
    if pattern is None:
        return False
    match = pattern.match(text.lstrip())
    return match is not None


def _has_residual_coordinator(text: str, profile: LinguisticProfile) -> bool:
    """Whether an unsplit conjunction still joins two statement-sized halves."""
    pattern = _cue_regex(profile.clause_coordinators)
    if pattern is None:
        return False
    for match in pattern.finditer(text):
        if (
            _token_count(text[: match.start()]) >= _MIN_CLAUSE_TOKENS
            and _token_count(text[match.end() :]) >= _MIN_CLAUSE_TOKENS
        ):
            return True
    return False


def _classify(
    text: str,
    provision: Provision,
    conditions: Sequence[str],
    quantities: Sequence[Quantity],
    profile: LinguisticProfile,
) -> PropositionType:
    """Assign the type that fixes how the proposition may later be checked.

    Order matters. A conditional statement is conditional even when it carries a
    number, because reporting it as a bare quantitative claim strips the
    antecedent — and an antecedent-free rendering of a conditional is the most
    common way a document is misquoted in good faith.
    """
    if provision.provision_type is ProvisionType.DEFINITION:
        return PropositionType.DEFINITIONAL
    if conditions:
        return PropositionType.CONDITIONAL
    if quantities:
        return PropositionType.QUANTITATIVE
    if _detect_temporal(text, profile) is not None:
        return PropositionType.TEMPORAL
    if provision.provision_type in {
        ProvisionType.PROCEDURE,
        ProvisionType.REPORTING_REQUIREMENT,
        ProvisionType.DELEGATION,
        ProvisionType.TRANSITIONAL,
    }:
        return PropositionType.PROCEDURAL
    return PropositionType.ASSERTION_OF_CONTENT


def _statement_type_for(prop_type: PropositionType, modality: Modality | None) -> StatementType:
    """Bridge to the shared vocabulary the claim layer evaluates against.

    Definitions map to ``interpretation`` rather than ``fact`` because a
    stipulated meaning is not a checkable assertion about the world; assumptions
    map to ``forecast`` because they are evaluated against their conditions, not
    graded true or false.
    """
    if prop_type is PropositionType.DEFINITIONAL:
        return StatementType.INTERPRETATION
    if prop_type is PropositionType.ASSUMPTION:
        return StatementType.FORECAST
    if modality in {Modality.OBLIGATORY, Modality.PROHIBITIVE, Modality.PERMISSIVE}:
        return StatementType.NORMATIVE
    if modality is Modality.PROPOSED or modality is Modality.HYPOTHETICAL:
        return StatementType.FORECAST
    return StatementType.FACT


def _tags_for(provision: Provision, prop_type: PropositionType) -> list[str]:
    tags = [provision.provision_type.value, prop_type.value]
    if provision.mechanism_type is not None:
        tags.append(provision.mechanism_type.value)
    return sorted(set(tags))


def _extraction_confidence(
    document: DocumentModel,
    *,
    atomic: bool,
    self_contained: bool,
    has_offsets: bool,
    quantified: bool,
    model_assisted: bool = False,
) -> Confidence:
    """Confidence that the DOCUMENT SAYS THIS, atomically and in this scope.

    Not confidence that the proposition is true of the world — that question
    belongs to the claim layer and is answered against external evidence. The
    figure is capped by the document's own extraction quality, because a
    proposition read off a badly-OCRed page cannot be more reliable than the page
    was, and a high number over unreadable text is the exact substitution of
    model confidence for evidence that Aleph exists to refuse.
    """
    score = 0.9
    basis = [
        ConfidenceBasis(
            factor=ConfidenceFactor.PRIMARY_SOURCE_COVERAGE,
            effect=ConfidenceEffect.RAISES,
            note="Anchored on a verbatim passage of the primary document.",
        )
    ]
    limiting: str | None = None

    if not has_offsets:
        score -= 0.05
        basis.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.PRIMARY_SOURCE_COVERAGE,
                effect=ConfidenceEffect.LOWERS,
                note="Character offsets unavailable; the passage is quotable but not located.",
            )
        )
    if not atomic:
        score -= 0.2
        limiting = "The passage still bundles more than one assertion."
        basis.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.CLAIM_AMBIGUITY,
                effect=ConfidenceEffect.LOWERS,
                note="Coordinated clauses could not be separated safely.",
            )
        )
    if not self_contained:
        score -= 0.15
        limiting = limiting or "An unresolved reference points outside the passage."
        basis.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.CLAIM_AMBIGUITY,
                effect=ConfidenceEffect.LOWERS,
                note="The text opens with a reference resolved elsewhere in the document.",
            )
        )
    if quantified:
        score += 0.03
        basis.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.QUANTITATIVE_VALIDATION,
                effect=ConfidenceEffect.RAISES,
                note="A figure was parsed with its verbatim source text preserved.",
            )
        )

    quality = document.source.extraction_quality.state
    cap = {
        ExtractionQualityState.GOOD: 1.0,
        ExtractionQualityState.DEGRADED: 0.75,
        ExtractionQualityState.POOR: 0.5,
        ExtractionQualityState.UNKNOWN: 0.8,
    }[quality]
    if score > cap:
        score = cap
        limiting = limiting or f"Text extraction quality for this document is '{quality.value}'."
        basis.append(
            ConfidenceBasis(
                factor=ConfidenceFactor.PRIMARY_SOURCE_COVERAGE,
                effect=ConfidenceEffect.LOWERS,
                note=f"Capped by document extraction quality '{quality.value}'.",
            )
        )

    return Confidence(
        evidence_confidence=round(max(0.0, min(1.0, score)), 3),
        model_confidence=0.7 if model_assisted else None,
        basis=basis,
        limiting_factor=limiting,
    )


def _parse_candidates(raw: str | dict[str, Any] | list[Any]) -> list[Mapping[str, Any]]:
    """Normalise whatever a provider returned into a list of candidate mappings.

    Providers differ: some return parsed JSON, some a string, some a string
    wrapped in a code fence. All three are handled, and anything unparseable
    yields an empty list — which triggers the rule-based fallback rather than an
    exception, because a malformed model response is an ordinary event and must
    not be able to fail a run.
    """
    payload: Any = raw
    # Aleph's concrete LLMProvider returns an auditable LLMResponse rather than
    # a bare dictionary. Protocol-only test providers commonly return the bare
    # payload, so accept both without importing the provider package here.
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
            return []
    if isinstance(payload, Mapping):
        payload = payload.get("propositions", [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, Mapping)]


def _fold(text: str) -> str:
    """Accent-folded, casefolded form. Shared with the graph's entity resolver."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


# Re-exported for :mod:`aleph.propositions.graph` and
# :mod:`aleph.retrieval.vocabulary`, which must fold identically or they will
# disagree about whether two spellings are the same entity.
fold_text = _fold
