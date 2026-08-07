"""Pulling checkable assertions out of coverage, and keeping identity beside them.

A news article is not a set of claims. It is a set of claims wrapped in the
apparatus of attribution — "the ministry's spokesperson told this paper that the
levy would raise 200 million" — and the wrapping is doing three different jobs at
once. It tells you what was asserted, it tells you who asserted it, and it tells
you who is relaying it. Aleph needs all three, and needs them in *separate
fields*, because the next stage of the pipeline has to be able to remove the
second and third without touching the first.

That separation is the organising principle of this module and the reason it
exists as its own step rather than as a prompt. Each :class:`ExtractedClaim`
carries:

* ``text`` — the assertion alone, verbatim, with the attributive frame removed;
* ``source_sentence`` — the whole original sentence, kept so a reader can check
  that the unwrapping did not change what was said;
* ``provenance`` — a :class:`ClaimProvenance` holding speaker, role, outlet,
  author and timestamp, in fields that :mod:`aleph.claims.blind` knows how to
  strip and that :class:`~aleph.core.models.RedactedClaimContext` structurally
  cannot accept.

If identity were left inside the claim string, blinding would be a
search-and-replace over prose with no ground truth to check itself against. By
recording who was named *at the moment we noticed them*, extraction hands the
redactor an exact list of what to remove and the verifier an exact list of what
to look for afterwards. :attr:`ExtractionResult.identity_vocabulary` is that
list, and it is discovered from the corpus rather than looked up: Aleph carries
no roster of politicians, parties or outlets anywhere, and must work on a dispute
in a country it has never seen.

**What counts as a claim.** Four forms, all recorded:

* direct quotation — text inside quote marks, attributed or not;
* indirect quotation — a reporting verb plus a ``that``/``que`` complement;
* attributed statement — "according to X, …", where the assertion is the
  main clause;
* bare assertion — a declarative sentence the article states in its own voice,
  which is a claim by the outlet and is treated as one.

Quantitative assertions are not a fifth form but a property: any of the four can
carry numbers, and when it does the figures are parsed into
:class:`~aleph.core.models.Quantity` and :class:`~aleph.core.models.Money` with
their verbatim source text preserved, so the arithmetic can be re-checked later
rather than taken on trust.

**Extraction is deliberately generous.** A sentence that might be a claim is
recorded; deciding it is an opinion, or unverifiable, happens downstream and is a
publishable result. The opposite policy — dropping anything doubtful at
extraction — would silently narrow what the analysis ever considered, and the
narrowing would be invisible in the output.

**Offline by construction.** The rule-based path is the baseline and always runs.
A :class:`ClaimLLMProvider` may be supplied to widen recall, and
:class:`aleph.llm.base.LLMProvider` satisfies that protocol structurally — but
this module imports nothing from :mod:`aleph.llm`, never reaches the network, and
falls back to the rule engine with a recorded note if a provider errors or
returns something unparseable. :class:`DeterministicClaimProvider` is a real,
working offline implementation used for tests and for the demo bundle.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from aleph.claims.blind import (
    DEFAULT_ATTRIBUTION_VERBS,
    DEFAULT_HONORIFICS,
    SEMANTIC_KEEP,
    IdentityVocabulary,
)
from aleph.claims.classify import (
    ClaimClassification,
    classify_claim_text,
    detect_language,
)
from aleph.core.enums import (
    MoneyUnit,
    ProvenanceSourceKind,
    QuantityKind,
    StatementType,
)
from aleph.core.ids import claim_id as make_claim_id
from aleph.core.models import Money, Provenance, Quantity, Span

__all__ = [
    "EXTRACTOR_VERSION",
    "ClaimForm",
    "ClaimLLMProvider",
    "DeterministicClaimProvider",
    "ClaimProvenance",
    "ParsedNumber",
    "ExtractedClaim",
    "ExtractionNote",
    "ExtractionResult",
    "CLAIM_EXTRACTION_SCHEMA",
    "parse_numbers",
    "split_sentences",
    "extract_claims",
    "extract_from_article",
    "build_provenance",
    "merge_vocabularies",
    "absolute_value",
    "SCALE_MULTIPLIER",
]

#: Version of this extractor, recorded on every claim's provenance so a span can
#: be invalidated when the extraction rules change.
EXTRACTOR_VERSION: Final[str] = "aleph-claim-extractor/1.0.0"


# ---------------------------------------------------------------------------
# The LLM boundary
# ---------------------------------------------------------------------------


@runtime_checkable
class ClaimLLMProvider(Protocol):
    """The one thing this module needs from a language model.

    Declared structurally, and matching :class:`aleph.llm.base.LLMProvider`
    exactly, so a real provider can be passed in without this module importing
    the provider package. That keeps claim extraction runnable — and testable —
    with no model, no credentials and no network, which is the condition the rest
    of the pipeline is built to assume.
    """

    def complete(self, prompt: str, *, schema: Mapping[str, Any] | None = None) -> str:
        """Return a completion, JSON-shaped when ``schema`` is supplied."""
        ...


#: Response shape requested from a provider on the LLM-assisted path.
CLAIM_EXTRACTION_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "normalised_text": {"type": "string"},
                    "form": {
                        "type": "string",
                        "enum": [
                            "assertion",
                            "direct_quotation",
                            "indirect_quotation",
                            "attributed_statement",
                        ],
                    },
                    "speaker_name": {"type": ["string", "null"]},
                    "speaker_role": {"type": ["string", "null"]},
                    "source_sentence": {"type": "string"},
                },
                "required": ["text", "normalised_text", "form", "source_sentence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}

_EXTRACTION_PROMPT = """\
TASK: claim_extraction

Identify every checkable assertion in the passage below. Record the assertion
text separately from who made it: put the assertion in `text` with the
attributive frame removed, and the speaker's name and functional role in
`speaker_name` and `speaker_role`. Never merge the two. Include predictions,
opinions and value judgements as claims; classifying them happens later.
Preserve numbers exactly as written.

LANGUAGE: {language}

PASSAGE:
{passage}
"""


class DeterministicClaimProvider:
    """A real, offline provider that returns the same answer for the same input.

    Not a stub. It performs an actual second reading of the passage using a
    narrower rule than the main extractor — it looks only for reporting-verb
    constructions and treats the complement clause as the claim — so combining
    the two paths genuinely exercises the merge and de-duplication logic rather
    than echoing the rule engine back at itself.

    It exists so that the whole pipeline, including the LLM-assisted path, runs
    end to end with no credentials, no network and a byte-identical result on
    every machine. A demo that only works with a live model is a demo of the
    model.
    """

    name: Final[str] = "deterministic-offline"

    def complete(self, prompt: str, *, schema: Mapping[str, Any] | None = None) -> str:
        """Answer an Aleph task prompt with deterministic JSON."""
        if "TASK: claim_extraction" in prompt:
            return json.dumps({"claims": self._extract(prompt)}, ensure_ascii=False)
        if "TASK: evaluator_self_report" in prompt:
            return json.dumps(self._self_report(prompt), ensure_ascii=False)
        return json.dumps({"note": "unrecognised task", "handled": False}, ensure_ascii=False)

    @staticmethod
    def _extract(prompt: str) -> list[dict[str, Any]]:
        passage = prompt.split("PASSAGE:\n", 1)[-1].strip()
        out: list[dict[str, Any]] = []
        for sentence in split_sentences(passage):
            match = _INDIRECT_RE.search(sentence)
            if not match:
                continue
            claim_text = sentence[match.end() :].strip(" .")
            if len(claim_text.split()) < 3:
                continue
            speaker = _clean_speaker(match.group("speaker"))
            out.append(
                {
                    "text": claim_text,
                    "normalised_text": _normalise(claim_text),
                    "form": ClaimForm.INDIRECT_QUOTATION.value,
                    "speaker_name": (
                        speaker if speaker and _plausible_attribution(speaker) else None
                    ),
                    "speaker_role": _role_in(speaker) if speaker else None,
                    "source_sentence": sentence,
                }
            )
        return out

    @staticmethod
    def _self_report(prompt: str) -> dict[str, Any]:
        """Report a confidence derived from hedging density in the prompt.

        Deterministic and, unlike a constant, actually responsive to the input:
        heavily hedged material yields a lower self-report. It is still only a
        self-report, recorded as a diagnostic and never allowed to move evidence
        confidence.
        """
        words = max(1, len(prompt.split()))
        hedges = len(
            re.findall(
                r"\b(?:may|might|could|possibly|unclear|uncertain|podr[ií]a|quiz[aá]s|incierto)\b",
                prompt,
                re.IGNORECASE,
            )
        )
        confidence = max(0.05, min(0.9, 0.75 - 6.0 * hedges / words))
        return {
            "model_confidence": round(confidence, 3),
            "note": (
                "Deterministic offline self-report derived from hedging density. Diagnostic "
                "only: it describes the model's disposition, not the state of the evidence."
            ),
        }


# ---------------------------------------------------------------------------
# Claim forms and provenance
# ---------------------------------------------------------------------------


class ClaimForm(StrEnum):
    """How an assertion appeared in the source text.

    An extraction-internal vocabulary rather than part of the published contract:
    the data contract records ``statement_type`` (what kind of utterance it is),
    which is a different question from how it was packaged. Form matters here
    because it determines how much of the sentence is the claim and how much is
    the attribution to be peeled off.
    """

    ASSERTION = "assertion"
    """Stated by the article in its own voice. A claim by the outlet."""

    DIRECT_QUOTATION = "direct_quotation"
    """Inside quote marks. The strongest form: the words are the speaker's."""

    INDIRECT_QUOTATION = "indirect_quotation"
    """Reporting verb plus complement clause. The words are the reporter's."""

    ATTRIBUTED_STATEMENT = "attributed_statement"
    """'According to X, …'. Attribution without a reporting verb."""


@dataclass(frozen=True, slots=True)
class ClaimProvenance:
    """Everything about *who*, held apart from everything about *what*.

    This object is the reason blinding can be verified rather than merely
    performed. Each field here is a thing the blind evaluator must not see, and
    each was captured at the point of extraction, so the redactor is handed an
    exact target list and the leak checker an exact search list — instead of both
    having to guess which capitalised words in a sentence were a person.

    ``speaker_role`` is preferred over ``speaker_name`` wherever a role can be
    recovered, matching the rest of Aleph: roles are what the attributed stage
    should publish, and a role is not a private individual.
    """

    source_id: str
    source_kind: ProvenanceSourceKind
    speaker_name: str | None = None
    speaker_role: str | None = None
    outlet_name: str | None = None
    outlet_id: str | None = None
    author: str | None = None
    published_at: str | None = None
    made_at: str | None = None
    url: str | None = None
    article_id: str | None = None
    attribution_verb: str | None = None
    span: Span | None = None
    extractor: str = EXTRACTOR_VERSION

    def identities(self) -> tuple[str, ...]:
        """Every identity string this provenance names, for the redactor."""
        return tuple(
            value
            for value in (self.speaker_name, self.outlet_name, self.author)
            if value and value.strip()
        )

    def to_model(self) -> Provenance:
        """Render as the contract's :class:`~aleph.core.models.Provenance`.

        Note what does not survive: the speaker. The contract's provenance
        records where a claim was *found*, not who uttered it; the speaker
        belongs to the attributed stage and reaches it through
        :class:`ExtractedClaim`, never through a field the blind path could read.
        """
        return Provenance(
            source_id=self.source_id,
            source_kind=self.source_kind,
            url=self.url,
            retrieved_at=None,
            span=self.span,
            extractor=self.extractor,
        )


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParsedNumber:
    """One numeric expression recovered from text, with its verbatim source.

    ``raw_text`` is required by the data contract for exactly the reason it is
    kept here: decimal separators differ between locales, "1.200" is either one
    thousand two hundred or one point two, and a downstream arithmetic check that
    inherited the wrong reading would produce a confident, wrong verdict. Keeping
    the original string makes the transcription auditable.
    """

    value: float
    kind: QuantityKind
    raw_text: str
    char_start: int
    char_end: int
    unit: str | None = None
    currency: str | None = None
    scale: MoneyUnit | None = None
    ambiguous_separator: bool = False

    @property
    def is_money(self) -> bool:
        """Whether a currency was positively identified, not merely guessed."""
        return self.currency is not None

    def to_quantity(self) -> Quantity:
        """Render as a contract :class:`~aleph.core.models.Quantity`."""
        return Quantity(
            value=self.value,
            kind=self.kind,
            unit=self.unit,
            raw_text=self.raw_text,
        )

    def to_money(self, *, year: int | None = None) -> Money | None:
        """Render as :class:`~aleph.core.models.Money`, or ``None`` if not money.

        Returns ``None`` rather than inventing a currency. A bare ``$`` is
        ambiguous across jurisdictions and Aleph is document-agnostic, so an
        unresolvable currency is recorded as a quantity with a note instead of
        being assigned to whichever country the developer had in mind.
        """
        if self.currency is None:
            return None
        return Money(
            amount=self.value,
            currency=self.currency,
            unit=self.scale or MoneyUnit.UNIT,
            year=year,
            basis=None,
        )


# Three-letter uppercase tokens that are words, not ISO-4217 codes. Keeping this
# list, rather than an allow-list of currencies, is what keeps the parser
# document-agnostic: any real currency code works, in any jurisdiction.
_NOT_CURRENCY: Final[frozenset[str]] = frozenset(
    {
        "THE",
        "AND",
        "FOR",
        "NOT",
        "ALL",
        "NEW",
        "TWO",
        "ONE",
        "PER",
        "VAT",
        "GDP",
        "CPI",
        "LOS",
        "LAS",
        "POR",
        "QUE",
        "CON",
        "SIN",
        "DEL",
        "SUS",
        "PIB",
        "IVA",
        "IPC",
        "MAS",
        "SON",
        "ART",
        "NUM",
        "MIN",
        "MAX",
        "PDF",
    }
)

_CURRENCY_SYMBOLS: Final[Mapping[str, str]] = {"€": "EUR", "£": "GBP", "¥": "JPY"}

_SCALE_WORDS: Final[Mapping[str, MoneyUnit]] = {
    "thousand": MoneyUnit.THOUSAND,
    "mil": MoneyUnit.THOUSAND,
    "miles": MoneyUnit.THOUSAND,
    "million": MoneyUnit.MILLION,
    "millions": MoneyUnit.MILLION,
    "millon": MoneyUnit.MILLION,
    "millón": MoneyUnit.MILLION,
    "millones": MoneyUnit.MILLION,
    "billion": MoneyUnit.BILLION,
    "billions": MoneyUnit.BILLION,
    "mil millones": MoneyUnit.BILLION,
    "miles de millones": MoneyUnit.BILLION,
    "billon": MoneyUnit.BILLION,
    "billón": MoneyUnit.BILLION,
    "billones": MoneyUnit.BILLION,
}

# Grouped form first, and it REQUIRES at least one separator. With `*` the
# grouped branch matched the first three digits of a four-digit year, so "2027"
# was read as the quantity 202 -- a silent corruption of every arithmetic check
# downstream. The plain branch is greedy, so a bare run of digits is consumed
# whole and can then be recognised as a year and discarded.
_NUMBER_TOKEN: Final[str] = r"\d{1,3}(?:[.,\u00a0\u202f ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"

_PERCENT_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?P<num>{_NUMBER_TOKEN})\s*(?:%|por\s+ciento|per\s?cent|percent)",
    re.IGNORECASE,
)
_PP_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?P<num>{_NUMBER_TOKEN})\s*(?:puntos?\s+porcentuales?|percentage\s+points?|p\.?p\.?)\b",
    re.IGNORECASE,
)
# Scale words are case-insensitive; the three-letter currency CODE is not, and
# the distinction is load-bearing. With a global IGNORECASE, `\b[A-Z]{3}\b` also
# matches ordinary lowercase words, and "una 200" would be read as 200 in a
# currency called UNA. Scoped inline flags keep each part matching what it means.
_SCALE_ALT: Final[str] = (
    r"(?i:mil(?:es)?\s+de\s+millones|mil\s+millones|millones?|mill[oó]n"
    r"|billones?|bill[oó]n|thousand|millions?|billions?)"
)
_MONEY_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?:(?P<code_pre>\b[A-Z]{{3}}\b)|(?P<sym>[€£¥$]))\s*(?P<num>{_NUMBER_TOKEN})"
    rf"(?:\s*(?P<scale>{_SCALE_ALT}))?"
    rf"(?:\s*(?P<code_post>\b[A-Z]{{3}}\b))?",
    re.UNICODE,
)
_PLAIN_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?<![\w.,])(?P<num>{_NUMBER_TOKEN})(?:\s*(?P<scale>{_SCALE_ALT}))?",
    re.UNICODE,
)
_YEAR_RE: Final[re.Pattern[str]] = re.compile(r"^(?:1[5-9]|20|21)\d{2}$")


def _to_float(raw: str) -> tuple[float, bool]:
    """Parse a locale-ambiguous numeric string, reporting whether it was ambiguous.

    The rules, in order:

    * both separators present — the rightmost is the decimal point;
    * exactly one separator followed by exactly three digits — a thousands
      group. ``1,200`` is 1200 and ``1.200`` is 1200, in both locales, because a
      three-digit group is overwhelmingly grouping rather than a three-decimal
      fraction. When the integer part is a single digit the Spanish decimal
      reading is genuinely possible, so the value is returned *and* flagged
      ambiguous rather than silently preferred;
    * otherwise the separator is a decimal point, which is what makes ``12,5``
      twelve and a half rather than a hundred and twenty-five.

    Returns ``(value, ambiguous)``. The flag is propagated so an arithmetic check
    that depends on the reading can decline rather than guess — declining is a
    publishable result, a wrong transcription is not.
    """
    text = re.sub(r"[\s\u00a0\u202f\u2009]", "", raw).strip()
    ambiguous = False
    has_dot = "." in text
    has_comma = "," in text
    if has_dot and has_comma:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        head, _, tail = text.rpartition(",")
        if len(tail) == 3:
            ambiguous = len(head.replace(",", "")) < 2
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    elif has_dot:
        head, _, tail = text.rpartition(".")
        if len(tail) == 3:
            ambiguous = len(head.replace(".", "")) < 2
            text = text.replace(".", "")
    try:
        return float(text), ambiguous
    except ValueError:
        return 0.0, True


def _scale_for(token: str | None) -> MoneyUnit | None:
    """Map a scale word to its multiplier, folding accents and spacing."""
    if not token:
        return None
    key = re.sub(r"\s+", " ", _fold_text(token)).strip()
    return _SCALE_WORDS.get(key) or _SCALE_WORDS.get(key.replace("miles de ", "mil "))


def _fold_text(text: str) -> str:
    """Lowercase and drop combining marks."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def parse_numbers(text: str) -> tuple[ParsedNumber, ...]:
    """Recover every numeric expression in ``text``, richest form first.

    Percentages and percentage points are matched before money, and money before
    bare numbers, so that a figure is claimed by the most specific reader that
    fits and never counted twice. Four-digit values that look like years are
    dropped from the bare-number pass: treating "2026" as a quantity would flood
    every arithmetic check with noise.

    The parser never assigns a currency it cannot see. A bare ``$`` yields a
    quantity with ``unit='unspecified_currency'`` rather than a
    :class:`~aleph.core.models.Money`, because guessing which country's dollar is
    meant is precisely the jurisdiction-specific assumption Aleph must not make.
    """
    found: list[ParsedNumber] = []
    claimed: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return not any(start < c_end and c_start < end for c_start, c_end in claimed)

    for pattern, kind in (
        (_PERCENT_RE, QuantityKind.PERCENTAGE),
        (_PP_RE, QuantityKind.PERCENTAGE_POINT),
    ):
        for match in pattern.finditer(text):
            if not free(match.start(), match.end()):
                continue
            value, ambiguous = _to_float(match.group("num"))
            claimed.append((match.start(), match.end()))
            found.append(
                ParsedNumber(
                    value=value,
                    kind=kind,
                    raw_text=match.group(0),
                    char_start=match.start(),
                    char_end=match.end(),
                    unit="%" if kind is QuantityKind.PERCENTAGE else "pp",
                    ambiguous_separator=ambiguous,
                )
            )

    for match in _MONEY_RE.finditer(text):
        if not free(match.start(), match.end()):
            continue
        code = match.group("code_pre") or match.group("code_post")
        symbol = match.group("sym")
        currency: str | None = None
        if code and code.upper() not in _NOT_CURRENCY:
            currency = code.upper()
        elif symbol and symbol in _CURRENCY_SYMBOLS:
            currency = _CURRENCY_SYMBOLS[symbol]
        if currency is None and symbol != "$":
            continue
        value, ambiguous = _to_float(match.group("num"))
        claimed.append((match.start(), match.end()))
        found.append(
            ParsedNumber(
                value=value,
                kind=QuantityKind.OTHER if currency else QuantityKind.COUNT,
                raw_text=match.group(0).strip(),
                char_start=match.start(),
                char_end=match.end(),
                unit=None if currency else "unspecified_currency",
                currency=currency,
                scale=_scale_for(match.group("scale")),
                ambiguous_separator=ambiguous,
            )
        )

    for match in _PLAIN_RE.finditer(text):
        if not free(match.start(), match.end()):
            continue
        raw_num = match.group("num")
        if _YEAR_RE.match(raw_num.strip()) and not match.group("scale"):
            continue
        value, ambiguous = _to_float(raw_num)
        claimed.append((match.start(), match.end()))
        found.append(
            ParsedNumber(
                value=value,
                kind=QuantityKind.COUNT,
                raw_text=match.group(0).strip(),
                char_start=match.start(),
                char_end=match.end(),
                scale=_scale_for(match.group("scale")),
                ambiguous_separator=ambiguous,
            )
        )

    found.sort(key=lambda n: n.char_start)
    return tuple(found)


#: Multipliers for comparing figures written at different scales.
SCALE_MULTIPLIER: Final[Mapping[MoneyUnit, float]] = {
    MoneyUnit.UNIT: 1.0,
    MoneyUnit.THOUSAND: 1e3,
    MoneyUnit.MILLION: 1e6,
    MoneyUnit.BILLION: 1e9,
    MoneyUnit.PERCENT_OF_GDP: 1.0,
}


def absolute_value(number: ParsedNumber) -> float:
    """Return a figure with its scale word applied, for cross-source comparison."""
    return number.value * SCALE_MULTIPLIER.get(number.scale or MoneyUnit.UNIT, 1.0)


# ---------------------------------------------------------------------------
# Sentence and quotation machinery
# ---------------------------------------------------------------------------

_ABBREVIATIONS: Final[tuple[str, ...]] = (
    "sr.",
    "sra.",
    "srta.",
    "dr.",
    "dra.",
    "ing.",
    "lic.",
    "art.",
    "arts.",
    "no.",
    "núm.",
    "num.",
    "pág.",
    "pag.",
    "etc.",
    "ee.uu.",
    "mr.",
    "mrs.",
    "ms.",
    "prof.",
    "fig.",
    "vs.",
    "ca.",
    "p.ej.",
    "e.g.",
    "i.e.",
)
_SENTENCE_SPLIT: Final[re.Pattern[str]] = re.compile(
    r"(?<=[.!?…])[\s ]+(?=[\"“«¿¡(\[]?[A-ZÁÉÍÓÚÑÜ0-9])"
)
_QUOTE_RE: Final[re.Pattern[str]] = re.compile(
    r"[\"“«]\s*(?P<body>[^\"”»]{8,600}?)\s*[\"”»]",
)

_HONORIFIC_ALT: Final[str] = "|".join(
    sorted((re.escape(h) for h in DEFAULT_HONORIFICS), key=len, reverse=True)
)
_NAME_BODY: Final[str] = (
    r"(?:[A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñü'’-]{1,}"
    r"(?:\s+(?:de|del|la|las|los|van|von|da|di|dos|du|el)\s+|\s+)?){1,4}"
)
_NAMED_SPEAKER: Final[str] = rf"(?P<speaker>(?:(?:{_HONORIFIC_ALT})\.?\s+)?{_NAME_BODY})"

_VERB_ALT: Final[str] = "|".join(
    sorted((re.escape(v) for v in DEFAULT_ATTRIBUTION_VERBS), key=len, reverse=True)
)
_INDIRECT_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b{_NAMED_SPEAKER}\s+(?P<verb>(?i:{_VERB_ALT}))\s+(?i:that|que)\s+",
    re.UNICODE,
)
_ACCORDING_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b(?i:according\s+to|seg[uú]n)\s+{_NAMED_SPEAKER}\s*,\s*",
    re.UNICODE,
)
# Two patterns rather than one alternation: `_NAMED_SPEAKER` contains a named
# group, and a single pattern using it twice is a regex compilation error.
_QUOTE_ATTRIB_VERB_FIRST: Final[re.Pattern[str]] = re.compile(
    rf"[\"”»]\s*,?\s*(?P<verb>(?i:{_VERB_ALT}))\s+{_NAMED_SPEAKER}",
    re.UNICODE,
)
_QUOTE_ATTRIB_NAME_FIRST: Final[re.Pattern[str]] = re.compile(
    rf"[\"”»]\s*,?\s*{_NAMED_SPEAKER}\s+(?P<verb>(?i:{_VERB_ALT}))",
    re.UNICODE,
)
_QUOTE_ATTRIB_BEFORE: Final[re.Pattern[str]] = re.compile(
    rf"\b{_NAMED_SPEAKER}\s+(?P<verb>(?i:{_VERB_ALT}))\s*[:,]\s*[\"“«]",
    re.UNICODE,
)

#: Generic institutional function words. Used to recover a ROLE from an
#: attribution, which is what the attributed stage is allowed to publish. These
#: are common-noun descriptions of function in any polity, not offices of one.
_ROLE_WORDS: Final[tuple[str, ...]] = (
    "spokesperson",
    "spokesman",
    "spokeswoman",
    "minister",
    "secretary",
    "president",
    "director",
    "economist",
    "analyst",
    "senator",
    "deputy",
    "mayor",
    "governor",
    "chair",
    "chairman",
    "chairwoman",
    "researcher",
    "professor",
    "official",
    "representative",
    "leader",
    "adviser",
    "advisor",
    "vocero",
    "vocera",
    "portavoz",
    "ministro",
    "ministra",
    "secretario",
    "secretaria",
    "presidente",
    "presidenta",
    "director",
    "directora",
    "economista",
    "analista",
    "senador",
    "senadora",
    "diputado",
    "diputada",
    "alcalde",
    "alcaldesa",
    "gobernador",
    "gobernadora",
    "investigador",
    "investigadora",
    "dirigente",
    "asesor",
    "asesora",
    "titular",
)
_ROLE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:" + "|".join(_ROLE_WORDS) + r")\b", re.IGNORECASE | re.UNICODE
)

_SENTENCE_STARTERS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "a",
        "an",
        "this",
        "that",
        "these",
        "those",
        "it",
        "there",
        "he",
        "she",
        "they",
        "we",
        "his",
        "her",
        "their",
        "but",
        "and",
        "in",
        "on",
        "at",
        "for",
        "however",
        "meanwhile",
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "esto",
        "esta",
        "este",
        "ese",
        "esa",
        "sus",
        "su",
        "pero",
        "sin",
        "con",
        "por",
        "para",
        "en",
        "de",
        "del",
        "no",
        "si",
    }
)


def split_sentences(text: str) -> tuple[str, ...]:
    """Split a passage into sentences, protecting common abbreviations.

    Crude but predictable, and predictability is what matters: sentence
    boundaries decide what counts as one claim, and a splitter that behaved
    differently on the same text between runs would make claim ids unstable and
    two bundles undiffable.
    """
    if not text.strip():
        return ()
    protected = text
    for i, abbreviation in enumerate(_ABBREVIATIONS):
        protected = re.sub(re.escape(abbreviation), f"\x00{i}\x00", protected, flags=re.IGNORECASE)
    pieces = _SENTENCE_SPLIT.split(protected)
    out: list[str] = []
    for piece in pieces:
        restored = piece
        for i, abbreviation in enumerate(_ABBREVIATIONS):
            restored = restored.replace(f"\x00{i}\x00", abbreviation)
        cleaned = restored.strip()
        if cleaned:
            out.append(cleaned)
    return tuple(out)


def _clean_speaker(raw: str | None) -> str | None:
    """Trim an attribution capture down to the name it actually contains."""
    if not raw:
        return None
    cleaned = raw.strip().strip(",;:").strip()
    tokens = cleaned.split()
    while tokens and _fold_text(tokens[0]).strip(".") in {
        _fold_text(h) for h in DEFAULT_HONORIFICS
    }:
        tokens = tokens[1:]
    while tokens and tokens[0].lower() in _SENTENCE_STARTERS:
        tokens = tokens[1:]
    return " ".join(tokens) or None


def _plausible_attribution(candidate: str) -> bool:
    """Whether a capture is plausibly *some* named entity — person or body.

    The permissive test. Anything failing it is not recorded as a speaker at all,
    because a spurious "speaker" would enter the redaction vocabulary and then
    quietly delete an ordinary word from every claim in the corpus.
    """
    tokens = [t for t in candidate.split() if t]
    if not tokens:
        return False
    if not any(t[:1].isupper() for t in tokens):
        return False
    if all(_fold_text(t).strip(".,") in SEMANTIC_KEEP for t in tokens):
        return False
    if len(tokens) == 1 and _fold_text(tokens[0]) in _SENTENCE_STARTERS:
        return False
    return True


def _looks_like_name(candidate: str) -> bool:
    """Whether a capture is plausibly a *personal* name rather than a body.

    The strict test, used to sort a discovered attribution into the ``persons``
    or the ``organisations`` bucket of the identity vocabulary. Both are
    redacted; they differ only in the placeholder they leave behind, and getting
    that wrong costs readability rather than neutrality.
    """
    tokens = [t for t in candidate.split() if t]
    if not _plausible_attribution(candidate):
        return False
    if any(_fold_text(t).strip(".,") in SEMANTIC_KEEP for t in tokens):
        return False
    if _ROLE_RE.search(candidate):
        return False
    capitalised = [t for t in tokens if t[:1].isupper()]
    return len(capitalised) >= max(1, len(tokens) - 1)


def _role_in(candidate: str | None) -> str | None:
    """Return the institutional role named inside an attribution capture, if any."""
    if not candidate:
        return None
    match = _ROLE_RE.search(candidate)
    return match.group(0) if match else None


def _role_near(sentence: str, speaker: str | None) -> str | None:
    """Recover the role apposed to a name: 'X, president of the federation, …'.

    Roles usually sit outside the name capture, in apposition after it, and the
    role is what the attributed stage is permitted to publish — Aleph prefers
    "Municipal association president" to a private individual's name everywhere.
    Recovering it here is what makes that preference possible downstream.

    The window starts after the speaker's name, so a role can never come back
    carrying the name it was meant to replace.
    """
    if not speaker:
        return None
    direct = _role_in(speaker)
    if direct:
        return direct
    index = sentence.find(speaker)
    if index < 0:
        return None
    after = sentence[index + len(speaker) : index + len(speaker) + 90]
    match = _ROLE_RE.search(after)
    if match:
        clause = after[match.start() :].split(",")[0].strip(' .;:"”»')
        return clause[:70] or match.group(0)
    before = sentence[max(0, index - 70) : index]
    match = _ROLE_RE.search(before)
    return match.group(0) if match else None


_PRONOUN_FIX: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"^\s*(?:that|que)\s+", re.IGNORECASE), ""),
    (re.compile(r"\s{2,}"), " "),
)


def _normalise(text: str) -> str:
    """Restate a claim as a single checkable proposition.

    Deliberately conservative: it trims leading complementisers and collapses
    whitespace, and does not paraphrase. Rewriting a claim is how a system ends
    up evaluating a strawman, so :attr:`ExtractedClaim.text` is always kept
    beside this and the two can be compared.
    """
    out = text.strip().strip("—–-").strip()
    for pattern, repl in _PRONOUN_FIX:
        out = pattern.sub(repl, out)
    out = out.strip(" ,;:")
    if out and out[0].islower():
        out = out[0].upper() + out[1:]
    if out and out[-1] not in ".!?":
        out = out + "."
    return out


# ---------------------------------------------------------------------------
# Extraction results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtractionNote:
    """A recorded limitation of one extraction pass.

    Published rather than swallowed. "The provider returned unparseable JSON and
    we fell back to rules" is information a reader needs in order to know how much
    the claim set is worth.
    """

    code: str
    message: str
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {"code": self.code, "message": self.message, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ExtractedClaim:
    """One assertion, with its identity kept in a separate compartment.

    The invariant this class exists to hold: ``text`` and ``normalised_text``
    contain the assertion and nothing about who made it, while
    :attr:`provenance` contains who made it and nothing about whether it is true.
    Downstream, :mod:`aleph.claims.blind` gets the first pair and the redaction
    vocabulary built from the second, and :class:`RedactedClaimContext` refuses
    the second by construction.
    """

    id: str
    text: str
    """The assertion, verbatim, with the attributive frame removed."""
    normalised_text: str
    """The same assertion as a single checkable proposition."""
    source_sentence: str
    """The whole original sentence, kept so unwrapping can be audited."""
    form: ClaimForm
    provenance: ClaimProvenance
    classification: ClaimClassification
    span: Span
    context_excerpts: tuple[str, ...] = ()
    """Neighbouring sentences that make the claim interpretable. Supplied to the
    blind evaluator, and the main defence against over-redaction: a claim with
    context survives losing a name."""
    numbers: tuple[ParsedNumber, ...] = ()
    quantities: tuple[Quantity, ...] = ()
    money: tuple[Money, ...] = ()
    extraction_confidence: float = 0.6
    """Confidence that this IS a claim and was unwrapped correctly. Not
    confidence that it is true."""
    extractor: str = EXTRACTOR_VERSION
    notes: tuple[str, ...] = ()

    @property
    def statement_type(self) -> StatementType:
        """The classified kind of utterance."""
        return self.classification.statement_type

    @property
    def made_at(self) -> str | None:
        """When the claim was made — the only temporal fact the blind path sees."""
        return self.provenance.made_at or self.provenance.published_at

    def identities(self) -> tuple[str, ...]:
        """Identity strings this claim's provenance names."""
        return self.provenance.identities()

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping for diagnostics."""
        return {
            "id": self.id,
            "text": self.text,
            "normalised_text": self.normalised_text,
            "source_sentence": self.source_sentence,
            "form": self.form.value,
            "statement_type": self.statement_type.value,
            "made_at": self.made_at,
            "context_excerpts": list(self.context_excerpts),
            "quantities": [q.to_jsonable() for q in self.quantities],
            "money": [m.to_jsonable() for m in self.money],
            "extraction_confidence": self.extraction_confidence,
            "extractor": self.extractor,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ExtractionResult:
    """The claims found in one passage, plus what to strip before evaluating them.

    :attr:`identity_vocabulary` is the deliverable that makes the next stage
    possible. It is assembled from the names that actually occupied attribution
    slots in *this* text, which is why Aleph needs no roster of politicians and
    works on a corpus in a jurisdiction it has never seen.
    """

    claims: tuple[ExtractedClaim, ...] = ()
    identity_vocabulary: IdentityVocabulary = field(default_factory=IdentityVocabulary)
    notes: tuple[ExtractionNote, ...] = ()
    sentences_examined: int = 0
    llm_assisted: bool = False

    @property
    def type_counts(self) -> dict[str, int]:
        """How many claims of each statement type were found."""
        counts: dict[str, int] = {t.value: 0 for t in StatementType}
        for claim in self.claims:
            counts[claim.statement_type.value] += 1
        return counts

    @property
    def form_counts(self) -> dict[str, int]:
        """How many claims of each surface form were found."""
        counts: dict[str, int] = {f.value: 0 for f in ClaimForm}
        for claim in self.claims:
            counts[claim.form.value] += 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping for diagnostics."""
        return {
            "claims": [c.as_dict() for c in self.claims],
            "identity_vocabulary": {
                "persons": sorted(self.identity_vocabulary.persons),
                "organisations": sorted(self.identity_vocabulary.organisations),
                "outlets": sorted(self.identity_vocabulary.outlets),
                "authors": sorted(self.identity_vocabulary.authors),
            },
            "notes": [n.as_dict() for n in self.notes],
            "sentences_examined": self.sentences_examined,
            "llm_assisted": self.llm_assisted,
            "type_counts": self.type_counts,
            "form_counts": self.form_counts,
        }


# ---------------------------------------------------------------------------
# The extractor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Candidate:
    """An assertion located in the text, before classification and id assignment."""

    text: str
    source_sentence: str
    form: ClaimForm
    speaker_name: str | None
    speaker_role: str | None
    attribution_verb: str | None
    char_start: int
    char_end: int
    confidence: float
    origin: str


def _candidates_in_sentence(sentence: str, offset: int) -> list[_Candidate]:
    """Find every assertion in one sentence, in all four surface forms."""
    out: list[_Candidate] = []

    for match in _QUOTE_RE.finditer(sentence):
        body = match.group("body").strip()
        if len(body.split()) < 3:
            continue
        speaker = verb = None
        tail_start = max(0, match.end() - 1)
        after = _QUOTE_ATTRIB_VERB_FIRST.search(sentence, tail_start) or (
            _QUOTE_ATTRIB_NAME_FIRST.search(sentence, tail_start)
        )
        before = _QUOTE_ATTRIB_BEFORE.search(sentence[: match.start() + 1])
        if after:
            speaker = _clean_speaker(after.group("speaker"))
            verb = after.group("verb")
        elif before:
            speaker = _clean_speaker(before.group("speaker"))
            verb = before.group("verb")
        role = _role_near(sentence, speaker)
        out.append(
            _Candidate(
                text=body,
                source_sentence=sentence,
                form=ClaimForm.DIRECT_QUOTATION,
                speaker_name=speaker if speaker and _plausible_attribution(speaker) else None,
                speaker_role=role,
                attribution_verb=verb,
                char_start=offset + match.start("body"),
                char_end=offset + match.end("body"),
                confidence=0.9 if speaker else 0.75,
                origin="rules.direct_quotation",
            )
        )

    if not out:
        indirect = _INDIRECT_RE.search(sentence)
        if indirect:
            body = sentence[indirect.end() :].strip(" .")
            if len(body.split()) >= 3:
                speaker = _clean_speaker(indirect.group("speaker"))
                out.append(
                    _Candidate(
                        text=body,
                        source_sentence=sentence,
                        form=ClaimForm.INDIRECT_QUOTATION,
                        speaker_name=(
                            speaker if speaker and _plausible_attribution(speaker) else None
                        ),
                        speaker_role=_role_near(sentence, speaker),
                        attribution_verb=indirect.group("verb"),
                        char_start=offset + indirect.end(),
                        char_end=offset + len(sentence),
                        confidence=0.8,
                        origin="rules.indirect_quotation",
                    )
                )

    if not out:
        according = _ACCORDING_RE.search(sentence)
        if according:
            body = sentence[according.end() :].strip(" .")
            if len(body.split()) >= 3:
                speaker = _clean_speaker(according.group("speaker"))
                out.append(
                    _Candidate(
                        text=body,
                        source_sentence=sentence,
                        form=ClaimForm.ATTRIBUTED_STATEMENT,
                        speaker_name=(
                            speaker if speaker and _plausible_attribution(speaker) else None
                        ),
                        speaker_role=_role_near(sentence, speaker),
                        attribution_verb=None,
                        char_start=offset + according.end(),
                        char_end=offset + len(sentence),
                        confidence=0.75,
                        origin="rules.attributed_statement",
                    )
                )

    if not out and len(sentence.split()) >= 5:
        # The article's own voice. Recorded because an outlet's unattributed
        # assertion is a claim by the outlet, and excluding it would exempt
        # exactly the statements no one is on the record for.
        out.append(
            _Candidate(
                text=sentence,
                source_sentence=sentence,
                form=ClaimForm.ASSERTION,
                speaker_name=None,
                speaker_role=None,
                attribution_verb=None,
                char_start=offset,
                char_end=offset + len(sentence),
                confidence=0.55,
                origin="rules.assertion",
            )
        )
    return out


def _normalise_language(tag: str | None) -> str | None:
    """Reduce a BCP-47 tag to the bare subtag the cue sets are keyed on.

    ``'es-CL'`` and ``'es'`` must weight the same cues; without this a regional
    tag silently down-weights every cue in its own language, which would then
    look like a classification failure rather than a plumbing one.
    """
    if not tag:
        return None
    base = tag.strip().lower().split("-")[0]
    return base if base in {"es", "en"} else "xx"


def _dedupe_key(text: str) -> str:
    """Key for treating two extractions of the same assertion as one."""
    folded = _fold_text(text)
    return re.sub(r"[^a-z0-9 ]+", "", folded).strip()


def build_provenance(
    *,
    source_id: str,
    source_kind: ProvenanceSourceKind,
    candidate: _Candidate,
    outlet_name: str | None,
    outlet_id: str | None,
    author: str | None,
    published_at: str | None,
    made_at: str | None,
    url: str | None,
    article_id: str | None,
    span: Span,
) -> ClaimProvenance:
    """Assemble the identity compartment for one extracted claim."""
    return ClaimProvenance(
        source_id=source_id,
        source_kind=source_kind,
        speaker_name=candidate.speaker_name,
        speaker_role=candidate.speaker_role,
        outlet_name=outlet_name,
        outlet_id=outlet_id,
        author=author,
        published_at=published_at,
        made_at=made_at or published_at,
        url=url,
        article_id=article_id,
        attribution_verb=candidate.attribution_verb,
        span=span,
    )


def extract_claims(
    text: str,
    *,
    source_id: str,
    source_kind: ProvenanceSourceKind = ProvenanceSourceKind.ARTICLE,
    outlet_name: str | None = None,
    outlet_id: str | None = None,
    author: str | None = None,
    published_at: str | None = None,
    made_at: str | None = None,
    url: str | None = None,
    article_id: str | None = None,
    language: str | None = None,
    provider: ClaimLLMProvider | None = None,
    id_scope: str | None = None,
    start_index: int = 1,
    page: int | None = None,
    context_window: int = 1,
    reference_year: int | None = None,
) -> ExtractionResult:
    """Extract claims from a passage of news text or a public statement.

    The rule-based pass always runs and is the baseline. When ``provider`` is
    supplied, its claims are merged in and de-duplicated against the rule-based
    ones; a provider that fails, times out or returns unparseable output is
    recorded as an :class:`ExtractionNote` and the rule-based result stands. The
    function therefore has the same shape offline as online, which is what makes
    the offline bundle a faithful demonstration rather than a different product.

    Args:
        text: The passage. May be a headline, a paragraph or a whole body.
        source_id: Id of the artefact this text came from, for provenance.
        source_kind: What sort of artefact that is.
        outlet_name: Publisher name. Recorded in provenance and added to the
            identity vocabulary so redaction removes it from the prose too.
        outlet_id: Publisher id, ``src:``-prefixed.
        author: Byline, if any. Treated as identity.
        published_at: Publication date or timestamp, ISO-8601.
        made_at: When the statement was made, if it differs from publication.
        url: Location of the source.
        article_id: ``art:``-prefixed id, when the passage is an article body.
        language: Override for language detection.
        provider: Optional LLM-assisted path.
        id_scope: Scope component for generated claim ids.
        start_index: First claim number, for stable ids across a multi-passage run.
        page: Page number for the recorded spans, when the source is paginated.
        context_window: How many neighbouring sentences to carry as interpretive
            context. Context is the antidote to over-redaction: a claim that
            keeps its surroundings survives losing a name.
        reference_year: Reference year for monetary figures, when the caller
            knows it. Never inferred from a clock.

    Returns:
        An :class:`ExtractionResult` with the claims and the identity vocabulary
        discovered from this passage.
    """
    lang = _normalise_language(language) or detect_language(text)
    sentences = split_sentences(text)
    notes: list[ExtractionNote] = []

    offsets: list[int] = []
    cursor = 0
    for sentence in sentences:
        found = text.find(sentence, cursor)
        if found < 0:
            found = cursor
        offsets.append(found)
        cursor = found + len(sentence)

    candidates: list[tuple[_Candidate, int]] = []
    for index, sentence in enumerate(sentences):
        for candidate in _candidates_in_sentence(sentence, offsets[index]):
            candidates.append((candidate, index))

    llm_used = False
    if provider is not None:
        llm_candidates, llm_notes = _provider_candidates(provider, text, lang, sentences, offsets)
        notes.extend(llm_notes)
        llm_used = not any(note.code == "provider_failed" for note in llm_notes)
        candidates.extend(llm_candidates)

    seen: dict[str, int] = {}
    merged: list[tuple[_Candidate, int]] = []
    for candidate, index in candidates:
        key = _dedupe_key(candidate.text)
        if not key:
            continue
        existing = seen.get(key)
        if existing is not None:
            # Keep the reading with the higher extraction confidence; a direct
            # quotation beats a paraphrase of the same words.
            if candidate.confidence > merged[existing][0].confidence:
                merged[existing] = (candidate, index)
            continue
        seen[key] = len(merged)
        merged.append((candidate, index))

    claims: list[ExtractedClaim] = []
    persons: set[str] = set()
    organisations: set[str] = set()

    for number, (candidate, sentence_index) in enumerate(merged, start=start_index):
        classification = classify_claim_text(candidate.text, language=lang)
        numbers = parse_numbers(candidate.text)
        quantities = tuple(n.to_quantity() for n in numbers if not n.is_money)
        money = tuple(
            m for m in (n.to_money(year=reference_year) for n in numbers if n.is_money) if m
        )
        span = Span(
            page=page,
            section_id=None,
            char_start=candidate.char_start,
            char_end=candidate.char_end,
            text=candidate.source_sentence,
        )
        provenance = build_provenance(
            source_id=source_id,
            source_kind=source_kind,
            candidate=candidate,
            outlet_name=outlet_name,
            outlet_id=outlet_id,
            author=author,
            published_at=published_at,
            made_at=made_at,
            url=url,
            article_id=article_id,
            span=span,
        )
        claim_notes: list[str] = [f"origin={candidate.origin}"]
        if any(n.ambiguous_separator for n in numbers):
            claim_notes.append(
                "a figure uses an ambiguous decimal separator; the arithmetic check "
                "will decline rather than assume a locale"
            )
        if any(n.unit == "unspecified_currency" for n in numbers):
            claim_notes.append(
                "a monetary symbol was found without a currency code; recorded as a "
                "quantity rather than assigned a currency"
            )

        context = _context_for(sentences, sentence_index, context_window)
        claims.append(
            ExtractedClaim(
                id=make_claim_id(number, scope=id_scope),
                text=candidate.text.strip(),
                normalised_text=_normalise(candidate.text),
                source_sentence=candidate.source_sentence,
                form=candidate.form,
                provenance=provenance,
                classification=classification,
                span=span,
                context_excerpts=context,
                numbers=numbers,
                quantities=quantities,
                money=money,
                extraction_confidence=candidate.confidence,
                notes=tuple(claim_notes),
            )
        )
    # Sort every discovered attribution into a bucket. Both are redacted; the
    # split decides only which placeholder replaces them, so a misfiling here
    # costs readability and never neutrality.
    for candidate, _ in merged:
        name = candidate.speaker_name
        if not name:
            continue
        if _looks_like_name(name):
            persons.add(name)
        else:
            organisations.add(name)

    vocabulary = IdentityVocabulary.build(
        persons=persons,
        organisations=organisations,
        outlets=[outlet_name] if outlet_name else [],
        authors=[author] if author else [],
    )

    if not claims and sentences:
        notes.append(
            ExtractionNote(
                code="no_claims_found",
                message=(
                    "no assertion could be isolated from this passage; recorded as a gap "
                    "rather than as an absence of claims"
                ),
                detail=f"{len(sentences)} sentence(s) examined",
            )
        )

    return ExtractionResult(
        claims=tuple(claims),
        identity_vocabulary=vocabulary,
        notes=tuple(notes),
        sentences_examined=len(sentences),
        llm_assisted=llm_used,
    )


def _context_for(sentences: Sequence[str], index: int, window: int) -> tuple[str, ...]:
    """Return the neighbouring sentences that make a claim interpretable."""
    if window <= 0:
        return ()
    start = max(0, index - window)
    end = min(len(sentences), index + window + 1)
    return tuple(sentences[i] for i in range(start, end) if i != index)


def _provider_candidates(
    provider: ClaimLLMProvider,
    text: str,
    language: str,
    sentences: Sequence[str],
    offsets: Sequence[int],
) -> tuple[list[tuple[_Candidate, int]], list[ExtractionNote]]:
    """Run the LLM-assisted path, degrading to nothing on any failure.

    Every failure mode is recorded and none propagates. A provider outage must
    not change what Aleph concludes, only how much it found — and the difference
    has to be visible in the output rather than absorbed.
    """
    notes: list[ExtractionNote] = []
    prompt = _EXTRACTION_PROMPT.format(language=language, passage=text)
    try:
        raw = provider.complete(prompt, schema=CLAIM_EXTRACTION_SCHEMA)
    except Exception as exc:  # noqa: BLE001 - any provider failure degrades to rules
        notes.append(
            ExtractionNote(
                code="provider_failed",
                message="LLM-assisted extraction failed; rule-based extraction stands",
                detail=f"{type(exc).__name__}: {exc}",
            )
        )
        return [], notes

    try:
        payload = json.loads(raw)
        entries = payload["claims"]
        if not isinstance(entries, list):
            raise TypeError("claims is not a list")
    except (ValueError, KeyError, TypeError) as exc:
        notes.append(
            ExtractionNote(
                code="provider_unparseable",
                message="provider response did not match the requested schema; ignored",
                detail=f"{type(exc).__name__}: {exc}",
            )
        )
        return [], notes

    out: list[tuple[_Candidate, int]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        claim_text = str(entry.get("text", "")).strip()
        source_sentence = str(entry.get("source_sentence", claim_text)).strip()
        if len(claim_text.split()) < 3:
            continue
        try:
            form = ClaimForm(str(entry.get("form", ClaimForm.ASSERTION.value)))
        except ValueError:
            form = ClaimForm.ASSERTION
        index = _sentence_index_for(source_sentence, sentences)
        start = offsets[index] if 0 <= index < len(offsets) else text.find(claim_text)
        speaker = entry.get("speaker_name")
        out.append(
            (
                _Candidate(
                    text=claim_text,
                    source_sentence=source_sentence or claim_text,
                    form=form,
                    speaker_name=str(speaker) if speaker else None,
                    speaker_role=(
                        str(entry["speaker_role"]) if entry.get("speaker_role") else None
                    ),
                    attribution_verb=None,
                    char_start=max(0, start),
                    char_end=max(0, start) + len(claim_text),
                    # Below every rule-based confidence on purpose: a model
                    # reading is a hypothesis about the text, and where the two
                    # paths disagree the one anchored in an explicit pattern wins.
                    confidence=0.5,
                    origin="llm",
                ),
                max(0, index),
            )
        )
    return out, notes


def _sentence_index_for(sentence: str, sentences: Sequence[str]) -> int:
    """Locate a provider-returned sentence among the rule-split ones."""
    key = _dedupe_key(sentence)
    for i, candidate in enumerate(sentences):
        if _dedupe_key(candidate) == key:
            return i
    for i, candidate in enumerate(sentences):
        if key and key in _dedupe_key(candidate):
            return i
    return 0


def extract_from_article(
    article: Any,
    body: str,
    *,
    provider: ClaimLLMProvider | None = None,
    id_scope: str | None = None,
    start_index: int = 1,
    reference_year: int | None = None,
) -> ExtractionResult:
    """Extract claims from a :class:`~aleph.core.models.NewsArticle` and its body.

    The headline is extracted alongside the body and never instead of it.
    Headline framing routinely diverges from what the article goes on to say, and
    that divergence is itself a finding — so the headline is treated as a claim by
    the outlet, in the outlet's own voice, and can be checked like any other.

    ``article`` is typed loosely so this module needs no import from the news
    package; anything with the ``NewsArticle`` field names works.
    """
    publisher = getattr(article, "publisher", None)
    outlet_name = getattr(publisher, "name", None)
    outlet_id = getattr(publisher, "id", None)
    headline = getattr(article, "headline", "") or ""
    dek = getattr(article, "dek", None) or ""
    passage = "\n".join(part for part in (headline, dek, body) if part).strip()

    return extract_claims(
        passage,
        source_id=getattr(article, "id", "art:unknown:0"),
        source_kind=ProvenanceSourceKind.ARTICLE,
        outlet_name=outlet_name,
        outlet_id=outlet_id,
        author=getattr(article, "author", None),
        published_at=getattr(article, "published_at", None),
        url=getattr(article, "url", None),
        article_id=getattr(article, "id", None),
        language=getattr(article, "language", None),
        provider=provider,
        id_scope=id_scope,
        start_index=start_index,
        reference_year=reference_year,
    )


def merge_vocabularies(results: Iterable[ExtractionResult]) -> IdentityVocabulary:
    """Union the identity vocabularies discovered across several passages.

    The corpus-level vocabulary is strictly better than any single passage's: a
    speaker named in full in one article and by surname alone in another is only
    redacted correctly from both once the two readings are pooled.
    """
    vocabulary = IdentityVocabulary()
    for result in results:
        vocabulary = vocabulary.merge(result.identity_vocabulary)
    return vocabulary
