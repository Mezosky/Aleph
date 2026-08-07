"""Removing identity from a claim before anyone decides whether it is true.

This is the module Aleph's central promise rests on. Everywhere else in the
system, speaker-blindness is enforced by a *type*:
:class:`~aleph.core.models.RedactedClaimContext` is frozen, forbids extra fields,
and has nowhere to put a speaker, a party, a coalition, a
government-or-opposition status or an outlet. That type closes the structural
door. This module closes the textual one, because a context object with no
speaker field still leaks the speaker if the claim reads "the minister's own
department says the levy will raise 200 million" or if an evidence excerpt is
titled with the name of the paper that ran it.

So redaction here is not string hygiene. It is the second half of a two-part
guarantee, and it is built to be *checked* rather than trusted:

* :func:`redact_text` replaces identity terms with neutral placeholders that
  preserve grammatical sense, so the sentence still parses and still means what
  it meant. ``[SPEAKER]``, ``[ORGANISATION]``, ``[OUTLET]`` — never a deletion,
  because a hole in a sentence changes its scope silently.
* :func:`leak_report` and :func:`assert_no_identity_leak` scan the finished
  context for any identity that survived, and the second raises
  :class:`~aleph.core.errors.NeutralityViolationError`. A redactor with no
  verifier is a claim about a redactor.
* :func:`assess_interpretability` guards the *other* failure. Over-redaction is
  a bug, not a safe default: a claim reduced to "[SPEAKER] said [ORGANISATION]
  would [REDACTED] by [NUMBER]" cannot be evaluated, and an unevaluable claim
  quietly becomes an ``unverifiable`` verdict that looks like a finding about the
  world when it is really a finding about the redactor. The boundary is drawn
  explicitly in :data:`SEMANTIC_KEEP` and enforced numerically.

**Where the boundary sits.** What must go is *attribution*: who spoke, which
party or coalition they belong to, whether they sit with the government or
against it, which outlet carried them, who wrote it up. What must stay is
*subject matter*: which document, which policy instrument, which institution the
measure actually acts on, which period, which population, and every number. The
line is not always obvious and one case is worth stating. A word like
"government" is usually the *subject of the fact* — the body that will spend the
money or run the scheme — and stripping it destroys the claim; so it is not in
the default alignment vocabulary. Words like "oficialismo", "ruling party" or
"the opposition benches" describe *alignment* and nothing else, and they are.
A caller with a corpus where "government" genuinely functions as a side-label can
add it; the default refuses to guess.

**No fixed list of politicians.** :class:`IdentityVocabulary` is supplied by the
caller and is normally discovered from the corpus by
:mod:`aleph.claims.extract`. Nothing here names a person, a party, an outlet or a
country: a hard-coded roster would be jurisdiction-specific, would silently fail
on every name it had never heard of, and would encode exactly the kind of
political knowledge Aleph must not have.

**When identity is the fact.** Sometimes the question genuinely is "did this
actor say that?", and blanking the actor makes the question unanswerable. The
escape hatch is :class:`AttributionAtIssue`: it must be constructed deliberately,
it demands a written justification, and it does not restore names. It assigns
*stable pseudonyms* — ``[SUBJECT_1]``, ``[SUBJECT_2]`` — so the evaluator can
follow who is who across the claim and the evidence without learning who anyone
is. Reference survives; identity does not. The audit record says so, because the
``redaction_version`` recorded in the published bundle is suffixed when the hatch
was used.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from aleph.core.enums import WithheldCategory
from aleph.core.errors import NeutralityViolationError
from aleph.core.ids import stable_hash
from aleph.core.models import (
    DEFAULT_REDACTION_VERSION,
    DEFAULT_WITHHELD,
    EvidenceItem,
    EvidentialRelevance,
    RedactedClaimContext,
    SourceRef,
    Span,
)

__all__ = [
    "REDACTION_VERSION",
    "ATTRIBUTION_AT_ISSUE_SUFFIX",
    "IdentityCategory",
    "PLACEHOLDERS",
    "DEFAULT_HONORIFICS",
    "DEFAULT_ALIGNMENT_TERMS",
    "DEFAULT_ATTRIBUTION_VERBS",
    "SEMANTIC_KEEP",
    "MAX_PLACEHOLDER_DENSITY",
    "MIN_REMAINING_CONTENT_WORDS",
    "IdentityVocabulary",
    "RedactionPolicy",
    "Replacement",
    "RedactionOutcome",
    "InterpretabilityReport",
    "LeakHit",
    "LeakReport",
    "AttributionAtIssue",
    "SourceAlias",
    "Blinding",
    "BlindingBatch",
    "ClaimLike",
    "withheld_for",
    "redact_text",
    "redact_evidence_item",
    "blind_claim",
    "redact_claim",
    "assess_interpretability",
    "leak_report",
    "assert_no_identity_leak",
]

#: Version of this redaction component. Written into every
#: :class:`~aleph.core.models.RedactedClaimContext` so that a change in what gets
#: stripped is visible in the published record rather than invisible in a diff.
REDACTION_VERSION: Final[str] = DEFAULT_REDACTION_VERSION

#: Suffix appended when the attribution-at-issue hatch was used, so a reader of
#: the bundle can see that this one context was blinded under a different rule.
ATTRIBUTION_AT_ISSUE_SUFFIX: Final[str] = "+attribution-at-issue"


# ---------------------------------------------------------------------------
# What gets replaced, and with what
# ---------------------------------------------------------------------------


class IdentityCategory(StrEnum):
    """A kind of identity Aleph strips before factual evaluation.

    Distinct from :class:`~aleph.core.enums.WithheldCategory`, which is the
    published audit vocabulary. This one is the redactor's internal working set:
    it maps to a placeholder and to one or more withheld categories, and it
    exists so the leak report can say *what kind* of thing leaked rather than
    only that something did.
    """

    PERSON = "person"
    PARTY = "party"
    COALITION = "coalition"
    ORGANISATION = "organisation"
    OUTLET = "outlet"
    AUTHOR = "author"
    ALIGNMENT = "alignment"
    TITLE = "title"
    SUBJECT_PSEUDONYM = "subject_pseudonym"


#: Placeholder text for each category.
#:
#: Bracketed and uppercase so a placeholder is unmistakable in a rendered claim
#: and can never be read as part of the sentence. Each is a noun phrase, not a
#: gap: "[SPEAKER] said the levy rises" parses; "said the levy rises" does not,
#: and a parser — human or machine — that has to guess at a missing subject will
#: guess, which is the failure redaction exists to prevent.
PLACEHOLDERS: Final[Mapping[IdentityCategory, str]] = {
    IdentityCategory.PERSON: "[SPEAKER]",
    IdentityCategory.PARTY: "[PARTY]",
    IdentityCategory.COALITION: "[COALITION]",
    IdentityCategory.ORGANISATION: "[ORGANISATION]",
    IdentityCategory.OUTLET: "[OUTLET]",
    IdentityCategory.AUTHOR: "[AUTHOR]",
    IdentityCategory.ALIGNMENT: "[POLITICAL_ALIGNMENT]",
    IdentityCategory.TITLE: "[TITLE]",
    IdentityCategory.SUBJECT_PSEUDONYM: "[SUBJECT]",
}

#: Which published withheld-category each internal category satisfies.
_CATEGORY_TO_WITHHELD: Final[Mapping[IdentityCategory, WithheldCategory]] = {
    IdentityCategory.PERSON: WithheldCategory.SPEAKER_NAME,
    IdentityCategory.PARTY: WithheldCategory.PARTY,
    IdentityCategory.COALITION: WithheldCategory.COALITION,
    IdentityCategory.ORGANISATION: WithheldCategory.INSTITUTIONAL_AFFILIATION,
    IdentityCategory.OUTLET: WithheldCategory.OUTLET,
    IdentityCategory.AUTHOR: WithheldCategory.AUTHOR,
    IdentityCategory.ALIGNMENT: WithheldCategory.GOVERNMENT_OR_OPPOSITION_STATUS,
    IdentityCategory.TITLE: WithheldCategory.SPEAKER_ROLE,
    IdentityCategory.SUBJECT_PSEUDONYM: WithheldCategory.SPEAKER_NAME,
}

#: Honorifics and role titles that precede a name. Generic across jurisdictions:
#: these are grammatical address forms and institutional function words, not a
#: list of offices in any particular state.
DEFAULT_HONORIFICS: Final[frozenset[str]] = frozenset(
    {
        # address forms
        "mr",
        "mrs",
        "ms",
        "miss",
        "dr",
        "prof",
        "professor",
        "sir",
        "dame",
        "sr",
        "sra",
        "srta",
        "don",
        "dona",
        "doña",
        "ing",
        "lic",
        "abg",
        # institutional function words that commonly precede a personal name
        "minister",
        "ministro",
        "ministra",
        "secretary",
        "secretario",
        "secretaria",
        "president",
        "presidente",
        "presidenta",
        "senator",
        "senador",
        "senadora",
        "deputy",
        "diputado",
        "diputada",
        "mayor",
        "alcalde",
        "alcaldesa",
        "governor",
        "gobernador",
        "gobernadora",
        "director",
        "directora",
        "spokesperson",
        "vocero",
        "vocera",
        "portavoz",
        "chair",
        "chairman",
        "undersecretary",
        "subsecretario",
        "subsecretaria",
        "councillor",
        "concejal",
    }
)

#: Terms whose entire content is a government-versus-opposition alignment.
#:
#: Note what is NOT here: "government", "gobierno", "ministry", "ministerio",
#: "administration". Those routinely name the *body that acts* in a policy claim,
#: and removing them turns "the ministry will fund the scheme" into a sentence
#: with no agent. The rule this default encodes is that Aleph strips a side
#: label, not an institution. A caller whose corpus uses "the government" purely
#: as a factional marker can add it through :class:`IdentityVocabulary`.
DEFAULT_ALIGNMENT_TERMS: Final[frozenset[str]] = frozenset(
    {
        "oficialismo",
        "oficialista",
        "oficialistas",
        "opositor",
        "opositora",
        "opositores",
        "la oposicion",
        "la oposición",
        "bancada oficialista",
        "bancada opositora",
        "ruling party",
        "ruling coalition",
        "governing coalition",
        "the opposition",
        "opposition benches",
        "pro-government",
        "anti-government",
        "government backbenchers",
        "opposition parties",
    }
)

#: Verbs that introduce an attributed statement. Used to strip a leading
#: attributive frame that extraction left attached, e.g. "X warned that Y".
DEFAULT_ATTRIBUTION_VERBS: Final[frozenset[str]] = frozenset(
    {
        "said",
        "stated",
        "told",
        "argued",
        "warned",
        "claimed",
        "asserted",
        "noted",
        "added",
        "explained",
        "insisted",
        "declared",
        "announced",
        "dijo",
        "afirmo",
        "afirmó",
        "senalo",
        "señaló",
        "sostuvo",
        "aseguro",
        "aseguró",
        "declaro",
        "declaró",
        "indico",
        "indicó",
        "advirtio",
        "advirtió",
        "explico",
        "explicó",
        "agrego",
        "agregó",
        "manifesto",
        "manifestó",
        "planteo",
        "planteó",
    }
)

#: Vocabulary that must survive redaction no matter what a caller's identity
#: vocabulary says. These words carry the subject matter of policy claims; if a
#: discovered "organisation name" collides with one of them, the discovery was
#: wrong and preserving meaning wins.
SEMANTIC_KEEP: Final[frozenset[str]] = frozenset(
    {
        "government",
        "gobierno",
        "state",
        "estado",
        "ministry",
        "ministerio",
        "budget",
        "presupuesto",
        "law",
        "ley",
        "bill",
        "proyecto",
        "decree",
        "decreto",
        "regulation",
        "reglamento",
        "tax",
        "impuesto",
        "levy",
        "gravamen",
        "subsidy",
        "subsidio",
        "pension",
        "pensión",
        "benefit",
        "beneficio",
        "household",
        "hogar",
        "households",
        "hogares",
        "worker",
        "trabajador",
        "workers",
        "trabajadores",
        "company",
        "empresa",
        "companies",
        "empresas",
        "municipality",
        "municipio",
        "region",
        "región",
        "report",
        "informe",
        "document",
        "documento",
        "article",
        "articulo",
        "artículo",
        "section",
        "seccion",
        "sección",
        "committee",
        "comision",
        "comisión",
        "congress",
        "congreso",
        "parliament",
        "parlamento",
        "court",
        "tribunal",
        "agency",
        "agencia",
        "programme",
        "program",
        "programa",
        "fund",
        "fondo",
        "revenue",
        "recaudacion",
        "recaudación",
        "spending",
        "gasto",
        "deficit",
        "déficit",
        "inflation",
        "inflacion",
        "inflación",
        "growth",
        "crecimiento",
    }
)

#: Above this share of placeholder characters a claim is treated as over-redacted.
MAX_PLACEHOLDER_DENSITY: Final[float] = 0.35

#: Below this many non-placeholder content words a claim is uninterpretable.
MIN_REMAINING_CONTENT_WORDS: Final[int] = 3

_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"\[[A-Z][A-Z_0-9]*\]")
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"\d[\d.,]*")
_POSSESSIVE_RE: Final[re.Pattern[str]] = re.compile(r"(?:'s|’s)\b")

# Accent variants, so "Sanchez" in the vocabulary still matches "Sánchez" in the
# text (and the reverse). Building the char class is cheaper and far more
# predictable than trying to align offsets between a folded and an unfolded copy.
_ACCENT_CLASSES: Final[Mapping[str, str]] = {
    "a": "aáàâäã",
    "e": "eéèêë",
    "i": "iíìîï",
    "o": "oóòôöõ",
    "u": "uúùûü",
    "n": "nñ",
    "c": "cç",
    "y": "yý",
}


def _fold(text: str) -> str:
    """Lowercase and drop combining marks, for accent-insensitive comparison."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _accent_flexible(term: str) -> str:
    """Build a regex body matching ``term`` regardless of accents and case."""
    parts: list[str] = []
    for char in term:
        folded = _fold(char)
        if folded in _ACCENT_CLASSES:
            parts.append(f"[{_ACCENT_CLASSES[folded]}]")
        elif char.isspace():
            parts.append(r"\s+")
        else:
            parts.append(re.escape(char))
    return "".join(parts)


# ---------------------------------------------------------------------------
# The identity vocabulary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentityVocabulary:
    """The identities to strip, discovered from a corpus rather than hard-coded.

    Aleph must work on a document from any legal system, in any language, about
    any dispute. A built-in roster of politicians would fail silently on every
    name it had never heard of — and failing silently is the worst possible
    behaviour for a redactor, because the output *looks* blind. So the vocabulary
    is an input. :mod:`aleph.claims.extract` builds one by observing which names
    occupy attribution slots in the corpus, and a caller can merge in anything
    else it knows.

    ``preserve`` is the counterweight and matters as much as the rest: a term
    listed there is never replaced, whatever else claims it. It is how a caller
    protects a policy name that happens to look like an organisation.
    """

    persons: frozenset[str] = frozenset()
    parties: frozenset[str] = frozenset()
    coalitions: frozenset[str] = frozenset()
    organisations: frozenset[str] = frozenset()
    outlets: frozenset[str] = frozenset()
    authors: frozenset[str] = frozenset()
    alignment_terms: frozenset[str] = DEFAULT_ALIGNMENT_TERMS
    honorifics: frozenset[str] = DEFAULT_HONORIFICS
    preserve: frozenset[str] = frozenset()

    @classmethod
    def build(
        cls,
        *,
        persons: Iterable[str] = (),
        parties: Iterable[str] = (),
        coalitions: Iterable[str] = (),
        organisations: Iterable[str] = (),
        outlets: Iterable[str] = (),
        authors: Iterable[str] = (),
        alignment_terms: Iterable[str] | None = None,
        honorifics: Iterable[str] | None = None,
        preserve: Iterable[str] = (),
    ) -> IdentityVocabulary:
        """Construct a vocabulary from any iterables, dropping blanks."""

        def clean(values: Iterable[str]) -> frozenset[str]:
            return frozenset(v.strip() for v in values if v and v.strip())

        return cls(
            persons=clean(persons),
            parties=clean(parties),
            coalitions=clean(coalitions),
            organisations=clean(organisations),
            outlets=clean(outlets),
            authors=clean(authors),
            alignment_terms=(
                DEFAULT_ALIGNMENT_TERMS if alignment_terms is None else clean(alignment_terms)
            ),
            honorifics=DEFAULT_HONORIFICS if honorifics is None else clean(honorifics),
            preserve=clean(preserve),
        )

    def merge(self, other: IdentityVocabulary) -> IdentityVocabulary:
        """Return the union of two vocabularies."""
        return IdentityVocabulary(
            persons=self.persons | other.persons,
            parties=self.parties | other.parties,
            coalitions=self.coalitions | other.coalitions,
            organisations=self.organisations | other.organisations,
            outlets=self.outlets | other.outlets,
            authors=self.authors | other.authors,
            alignment_terms=self.alignment_terms | other.alignment_terms,
            honorifics=self.honorifics | other.honorifics,
            preserve=self.preserve | other.preserve,
        )

    def with_preserved(self, *terms: str) -> IdentityVocabulary:
        """Return a copy that additionally protects ``terms`` from replacement."""
        return replace(self, preserve=self.preserve | frozenset(t for t in terms if t.strip()))

    def categorised_terms(self) -> tuple[tuple[str, IdentityCategory], ...]:
        """Return every term with its category, longest first.

        Longest-first ordering is not cosmetic. "María Sánchez Gómez" must be
        replaced before "María", or the surname survives as a fragment next to a
        placeholder and the redaction reads as complete while leaking a name.
        """
        pairs: list[tuple[str, IdentityCategory]] = []
        for term in self.persons:
            pairs.append((term, IdentityCategory.PERSON))
        for term in self.parties:
            pairs.append((term, IdentityCategory.PARTY))
        for term in self.coalitions:
            pairs.append((term, IdentityCategory.COALITION))
        for term in self.organisations:
            pairs.append((term, IdentityCategory.ORGANISATION))
        for term in self.outlets:
            pairs.append((term, IdentityCategory.OUTLET))
        for term in self.authors:
            pairs.append((term, IdentityCategory.AUTHOR))
        for term in self.alignment_terms:
            pairs.append((term, IdentityCategory.ALIGNMENT))
        pairs.sort(key=lambda pair: (-len(pair[0]), pair[0]))
        return tuple(pairs)

    def all_terms(self) -> frozenset[str]:
        """Every identity term, of any category. Used by the leak verifier."""
        return frozenset(term for term, _ in self.categorised_terms())

    def __bool__(self) -> bool:
        return bool(self.all_terms())


# ---------------------------------------------------------------------------
# Policy and results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RedactionPolicy:
    """What this run of the redactor does, and what it refuses to do.

    Defaults are the strict ones. ``strict_interpretability`` is the only knob a
    caller usually touches: turning it on makes an over-redacted claim an error
    rather than a warning, which is what a CI gate wants and what an exploratory
    run does not.
    """

    categories: frozenset[IdentityCategory] = frozenset(IdentityCategory)
    strip_honorifics: bool = True
    strip_attributive_frame: bool = True
    """Remove a leading 'X said that …' frame, keeping only the proposition.
    Extraction normally does this; doing it again here is cheap insurance."""
    pseudonymise_sources: bool = True
    """Replace evidence source ids, publishers and urls with stable pseudonyms.
    A ``src:`` slug and a domain name are both outlet identity in disguise."""
    strict_interpretability: bool = False
    max_placeholder_density: float = MAX_PLACEHOLDER_DENSITY
    min_remaining_content_words: int = MIN_REMAINING_CONTENT_WORDS
    withheld: tuple[WithheldCategory, ...] = DEFAULT_WITHHELD
    redaction_version: str = REDACTION_VERSION


@dataclass(frozen=True, slots=True)
class Replacement:
    """One substitution the redactor made, located in the source text."""

    original: str
    placeholder: str
    category: IdentityCategory
    char_start: int
    char_end: int
    field_path: str = ""
    """Where the substitution happened, e.g. ``'claim_text'`` or
    ``'evidence[2].spans[0].text'``, so the record is navigable."""

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {
            "original": self.original,
            "placeholder": self.placeholder,
            "category": self.category.value,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "field_path": self.field_path,
        }


@dataclass(frozen=True, slots=True)
class RedactionOutcome:
    """A redacted string and the full account of how it got that way."""

    text: str
    replacements: tuple[Replacement, ...]
    preserved_hits: tuple[str, ...] = ()
    """Terms that matched the identity vocabulary but were kept because they were
    protected. Surfaced because a frequent collision here means the discovered
    vocabulary is picking up subject matter."""

    @property
    def changed(self) -> bool:
        """Whether anything was replaced at all."""
        return bool(self.replacements)


@dataclass(frozen=True, slots=True)
class InterpretabilityReport:
    """Whether a redacted claim still says enough to be evaluated.

    Over-redaction is a defect with a deceptive signature: the pipeline keeps
    running, the evaluator finds nothing to check, and the claim is published as
    ``unverifiable`` — a statement about the world that is really a statement
    about the redactor. This report exists so that failure has a name.
    """

    interpretable: bool
    placeholder_density: float
    remaining_content_words: int
    numbers_preserved: bool
    reasons: tuple[str, ...] = ()

    @property
    def over_redacted(self) -> bool:
        """True when the redacted text can no longer carry an evaluation."""
        return not self.interpretable

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {
            "interpretable": self.interpretable,
            "placeholder_density": round(self.placeholder_density, 4),
            "remaining_content_words": self.remaining_content_words,
            "numbers_preserved": self.numbers_preserved,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class LeakHit:
    """One identity term found surviving inside a supposedly blind context."""

    term: str
    field_path: str
    char_start: int
    char_end: int
    excerpt: str

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {
            "term": self.term,
            "field_path": self.field_path,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True, slots=True)
class LeakReport:
    """The verifier's finding: what identity, if any, survived redaction.

    Returned rather than raised by :func:`leak_report` so that a diagnostic run
    can enumerate every leak at once instead of stopping at the first.
    :func:`assert_no_identity_leak` is the enforcing wrapper.
    """

    hits: tuple[LeakHit, ...]
    fields_scanned: int
    terms_checked: int

    @property
    def clean(self) -> bool:
        """True when no identity term survived anywhere in the context."""
        return not self.hits

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {
            "clean": self.clean,
            "hits": [hit.as_dict() for hit in self.hits],
            "fields_scanned": self.fields_scanned,
            "terms_checked": self.terms_checked,
        }


@dataclass(frozen=True)
class AttributionAtIssue:
    """Deliberate request to evaluate a claim whose subject *is* an identity.

    Some questions are irreducibly about who said or did what: "did this actor
    state that figure in March?" Blanking the actor makes the question
    unanswerable, so an escape hatch is genuinely necessary. It is built to be
    hard to reach by accident and impossible to reach by default:

    * it must be constructed explicitly and passed by keyword;
    * ``justification`` must be a real sentence, checked at construction, so the
      reason survives into review rather than living in someone's memory;
    * it does **not** restore names. Each subject gets a stable pseudonym —
      ``[SUBJECT_1]``, ``[SUBJECT_2]`` — applied identically across the claim and
      every evidence excerpt.

    That last point is what makes the hatch safe. The evaluator can verify "did
    [SUBJECT_1] say X?" against evidence in which the same actor is also
    [SUBJECT_1], so reference is preserved and the question is answerable, while
    who [SUBJECT_1] actually is remains outside the factual path. Party,
    coalition, alignment and outlet are still stripped normally: only the
    referential thread is spared.

    Raises:
        ValueError: If no subjects are named, or the justification is missing or
            too short to be a reason.
    """

    question: str
    subjects: tuple[str, ...]
    justification: str
    requested_by: str

    def __post_init__(self) -> None:
        if not self.subjects or not any(s.strip() for s in self.subjects):
            raise ValueError(
                "AttributionAtIssue requires at least one subject: the hatch exists to "
                "keep a specific identity referable, and naming none would simply "
                "disable redaction"
            )
        if len(self.justification.strip()) < 20:
            raise ValueError(
                "AttributionAtIssue requires a written justification of at least 20 "
                "characters. Suspending the ordinary blindness rule is a decision that "
                "must be defensible in review, so the reason is recorded with the request"
            )
        if not self.question.strip():
            raise ValueError("AttributionAtIssue requires the question at issue to be stated")
        if not self.requested_by.strip():
            raise ValueError("AttributionAtIssue requires a requester for the audit record")

    def pseudonyms(self) -> tuple[tuple[str, str], ...]:
        """Return ``(subject, pseudonym)`` pairs, deterministically ordered.

        Sorted by folded text so the same corpus always produces the same
        assignment: a pseudonym that moved between runs would make two bundles
        incomparable for no reason.
        """
        cleaned = sorted({s.strip() for s in self.subjects if s.strip()}, key=_fold)
        return tuple((subject, f"[SUBJECT_{i}]") for i, subject in enumerate(cleaned, start=1))


@dataclass(frozen=True, slots=True)
class SourceAlias:
    """Mapping from a real evidence source to the pseudonym shown to the evaluator.

    Kept *outside* the :class:`~aleph.core.models.RedactedClaimContext` on
    purpose. The attributed stage needs it to say which outlet carried what; the
    blind stage must never see it, and a field on the context object would be a
    door.
    """

    real_source_id: str
    alias_source_id: str
    real_publisher: str | None
    evidence_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {
            "real_source_id": self.real_source_id,
            "alias_source_id": self.alias_source_id,
            "real_publisher": self.real_publisher,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class Blinding:
    """The redacted context plus every diagnostic produced while building it.

    The context alone is what the evaluator receives. Everything else here is for
    the auditor: what was replaced, what survived, whether the result is still
    interpretable, and which real source each pseudonym stands for.
    """

    context: RedactedClaimContext
    replacements: tuple[Replacement, ...]
    interpretability: InterpretabilityReport
    leaks: LeakReport
    source_aliases: tuple[SourceAlias, ...] = ()
    attribution_at_issue: AttributionAtIssue | None = None
    preserved_hits: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Render the diagnostics as a JSON-safe mapping.

        Deliberately excludes ``source_aliases``: rendering the alias table next
        to the blind context in a debug dump would put the outlet back beside the
        claim, which is the one adjacency this module exists to prevent.
        """
        return {
            "redaction_version": self.context.redaction_version,
            "withheld": [category.value for category in self.context.withheld],
            "replacements": [r.as_dict() for r in self.replacements],
            "interpretability": self.interpretability.as_dict(),
            "leaks": self.leaks.as_dict(),
            "attribution_at_issue": (
                None
                if self.attribution_at_issue is None
                else {
                    "question": self.attribution_at_issue.question,
                    "justification": self.attribution_at_issue.justification,
                    "requested_by": self.attribution_at_issue.requested_by,
                    "subject_count": len(self.attribution_at_issue.subjects),
                }
            ),
            "preserved_hits": list(self.preserved_hits),
        }


@runtime_checkable
class ClaimLike(Protocol):
    """Anything with the identity-free parts of a claim.

    Structural rather than nominal so that both
    :class:`~aleph.core.models.Claim` and
    :class:`~aleph.claims.extract.ExtractedClaim` can be blinded without this
    module importing either — and, more to the point, without a future claim type
    being able to sneak a ``speaker`` attribute past the redactor by inheriting
    from the wrong base.
    """

    @property
    def normalised_text(self) -> str:
        """The single checkable proposition."""
        ...

    @property
    def made_at(self) -> str | None:
        """When the claim was made, ISO-8601, or ``None``."""
        ...


# ---------------------------------------------------------------------------
# Text redaction
# ---------------------------------------------------------------------------

_FRAME_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _attributive_frame_pattern(verbs: frozenset[str]) -> re.Pattern[str]:
    """Compile (and cache) the pattern for a leading 'X said that …' frame."""
    key = "|".join(sorted(verbs))
    cached = _FRAME_RE_CACHE.get(key)
    if cached is None:
        verb_alt = "|".join(_accent_flexible(v) for v in sorted(verbs, key=len, reverse=True))
        cached = re.compile(
            rf"^\s*(?P<subject>(?:\[[A-Z][A-Z_0-9]*\]|[^\s,]+)(?:\s+[^\s,]+){{0,4}}?)"
            rf"\s+(?:{verb_alt})\s+(?:that|que)\s+",
            re.IGNORECASE | re.UNICODE,
        )
        _FRAME_RE_CACHE[key] = cached
    return cached


def _protected_spans(text: str, preserve: Iterable[str]) -> list[tuple[int, int]]:
    """Return character ranges that no replacement may touch."""
    spans: list[tuple[int, int]] = []
    for term in preserve:
        term = term.strip()
        if not term:
            continue
        pattern = re.compile(rf"\b{_accent_flexible(term)}\b", re.IGNORECASE | re.UNICODE)
        spans.extend((m.start(), m.end()) for m in pattern.finditer(text))
    return spans


def _overlaps(start: int, end: int, spans: Sequence[tuple[int, int]]) -> bool:
    """Whether ``[start, end)`` intersects any protected span."""
    return any(start < s_end and s_start < end for s_start, s_end in spans)


def redact_text(
    text: str,
    vocabulary: IdentityVocabulary,
    *,
    policy: RedactionPolicy | None = None,
    field_path: str = "",
    pseudonyms: Mapping[str, str] | None = None,
) -> RedactionOutcome:
    """Replace identity in ``text`` with placeholders that keep the sentence whole.

    The algorithm, in order, because the order is what makes it correct:

    1. Terms named in :attr:`IdentityVocabulary.preserve` and in
       :data:`SEMANTIC_KEEP` are located first and marked untouchable. Meaning
       beats zeal: a discovered "organisation" that is really the word "budget"
       must not be blanked.
    2. Explicit pseudonyms (the attribution-at-issue hatch) are applied next, so
       a subject that must stay referable never falls to a generic placeholder.
    3. Remaining identity terms are replaced longest-first, so a full name goes
       before a surname and no fragment survives beside a placeholder.
    4. An honorific immediately preceding a replaced name is absorbed into the
       same placeholder: "Minister [SPEAKER]" would restate the role that was
       just removed.
    5. English possessive ``'s`` is re-attached to the placeholder, because
       "[SPEAKER] plan" is ungrammatical and an ungrammatical claim invites a
       reader — or a model — to reconstruct the missing word.
    6. Any leading attributive frame is dropped last, once its subject is already
       a placeholder.

    Args:
        text: The string to redact.
        vocabulary: Identities to remove.
        policy: Which categories to act on and how. Defaults to the strict policy.
        field_path: Recorded on each :class:`Replacement` for the audit trail.
        pseudonyms: Optional ``{term: '[SUBJECT_n]'}`` overrides.

    Returns:
        A :class:`RedactionOutcome`. The input is never mutated and an empty
        string returns unchanged.
    """
    if not text:
        return RedactionOutcome(text=text, replacements=(), preserved_hits=())

    active = policy or RedactionPolicy()
    protected_terms = list(vocabulary.preserve) + sorted(SEMANTIC_KEEP)
    protected = _protected_spans(text, protected_terms)

    ordered: list[tuple[str, IdentityCategory, str]] = []
    if pseudonyms:
        for term, alias in sorted(pseudonyms.items(), key=lambda kv: (-len(kv[0]), kv[0])):
            ordered.append((term, IdentityCategory.SUBJECT_PSEUDONYM, alias))
    pseudonymised = {_fold(t) for t in (pseudonyms or {})}
    for term, category in vocabulary.categorised_terms():
        if category not in active.categories:
            continue
        if _fold(term) in pseudonymised:
            continue
        ordered.append((term, category, PLACEHOLDERS[category]))

    honorific_alt = ""
    if active.strip_honorifics and vocabulary.honorifics:
        honorific_alt = "|".join(
            _accent_flexible(h) for h in sorted(vocabulary.honorifics, key=len, reverse=True)
        )

    replacements: list[Replacement] = []
    preserved_hits: list[str] = []
    result = text
    # Offsets are recorded against the ORIGINAL text, so the audit record points
    # at the source a reviewer will be reading, not at an intermediate string.
    for term, category, placeholder in ordered:
        body = _accent_flexible(term)
        prefix = rf"(?:(?:{honorific_alt})\.?\s+)?" if honorific_alt else ""
        pattern = re.compile(
            rf"{prefix}\b{body}\b(?:'s|’s)?",
            re.IGNORECASE | re.UNICODE,
        )

        def substitute(
            match: re.Match[str],
            *,
            replacement_placeholder: str = placeholder,
            replacement_category: str = category,
        ) -> str:
            surface = match.group(0)
            original_start = _locate(text, surface, [r.char_start for r in replacements])
            if original_start is not None and _overlaps(
                original_start, original_start + len(surface), protected
            ):
                preserved_hits.append(surface)
                return surface
            out = replacement_placeholder
            if _POSSESSIVE_RE.search(surface):
                out = f"{replacement_placeholder}'s"
            replacements.append(
                Replacement(
                    original=surface,
                    placeholder=out,
                    category=replacement_category,
                    char_start=original_start if original_start is not None else match.start(),
                    char_end=(original_start + len(surface))
                    if original_start is not None
                    else match.end(),
                    field_path=field_path,
                )
            )
            return out

        result = pattern.sub(substitute, result)

    if active.strip_attributive_frame:
        # Only ever drop a frame whose SUBJECT is something we just blanked. A
        # frame like "the report stated that …" is evidential, not attributive,
        # and removing it would delete the pointer to the source the claim rests
        # on — over-redaction dressed up as neutrality.
        frame = _attributive_frame_pattern(DEFAULT_ATTRIBUTION_VERBS)
        match = frame.match(result)
        if match and _PLACEHOLDER_RE.search(match.group("subject") or ""):
            stripped = result[match.end() :]
            if stripped.strip():
                result = stripped[0].upper() + stripped[1:]

    return RedactionOutcome(
        text=result,
        replacements=tuple(replacements),
        preserved_hits=tuple(dict.fromkeys(preserved_hits)),
    )


def _locate(original: str, surface: str, already: Sequence[int]) -> int | None:
    """Find ``surface`` in the original text, skipping positions already recorded."""
    used = set(already)
    start = 0
    while True:
        found = original.find(surface, start)
        if found < 0:
            lowered = original.lower().find(surface.lower(), start)
            return lowered if lowered >= 0 and lowered not in used else None
        if found not in used:
            return found
        start = found + 1


# ---------------------------------------------------------------------------
# Evidence redaction
# ---------------------------------------------------------------------------


def _pseudonymous_source(ref: SourceRef, vocabulary: IdentityVocabulary) -> tuple[SourceRef, str]:
    """Return a source reference with the publisher's identity removed.

    Tier, independence, language and publication date all survive, because every
    one of them is evidentially relevant: what kind of artefact this is, whether
    it is an independent observation or a restatement, and when it was published
    all bear on the claim. The publisher name, the id slug and the URL do not,
    and each of the three is enough on its own to identify the outlet.

    The alias id is a hash of the real id, so the same source keeps the same
    alias across a run and corroboration counting still works.
    """
    digest = stable_hash("blinded-source", ref.id, length=10)
    alias_id = f"src:blinded-{digest}"
    title_outcome = redact_text(ref.title, vocabulary, field_path="source_ref.title")
    blinded = SourceRef(
        id=alias_id,
        title=title_outcome.text or "[SOURCE]",
        url=None,
        publisher=None,
        published_at=ref.published_at,
        tier=ref.tier,
        independence=ref.independence,
        language=ref.language,
    )
    return blinded, alias_id


def redact_evidence_item(
    item: EvidenceItem,
    vocabulary: IdentityVocabulary,
    *,
    policy: RedactionPolicy | None = None,
    index: int = 0,
    pseudonyms: Mapping[str, str] | None = None,
) -> tuple[EvidenceItem, tuple[Replacement, ...], SourceAlias | None]:
    """Return a copy of an evidence item with identity stripped from every string.

    Every free-text field is redacted, not only the headline statement: the
    quoted spans, the notes, and the question and reasoning inside
    :class:`~aleph.core.models.EvidentialRelevance` all routinely name a speaker
    or an outlet, and a leak in a supporting field is exactly as much of a leak
    as one in the statement.

    The item's own ``id``, its ``supports``/``contradicts`` links and its
    ``derived_from_evidence_id`` are preserved: those are ``ev:`` identifiers,
    they carry no outlet information, and the corroboration and syndication
    checks are useless without them.
    """
    active = policy or RedactionPolicy()
    path = f"evidence[{index}]"
    collected: list[Replacement] = []

    def scrub(value: str, suffix: str) -> str:
        outcome = redact_text(
            value,
            vocabulary,
            policy=active,
            field_path=f"{path}.{suffix}",
            pseudonyms=pseudonyms,
        )
        collected.extend(outcome.replacements)
        return outcome.text

    statement = scrub(item.statement, "statement")
    spans = [
        Span(
            page=span.page,
            section_id=span.section_id,
            char_start=span.char_start,
            char_end=span.char_end,
            text=scrub(span.text, f"spans[{i}].text"),
        )
        for i, span in enumerate(item.spans)
    ]
    relevance = EvidentialRelevance(
        question=scrub(item.evidential_relevance.question, "evidential_relevance.question"),
        relevance=item.evidential_relevance.relevance,
        can_establish=[
            scrub(entry, f"evidential_relevance.can_establish[{i}]")
            for i, entry in enumerate(item.evidential_relevance.can_establish)
        ],
        cannot_establish=[
            scrub(entry, f"evidential_relevance.cannot_establish[{i}]")
            for i, entry in enumerate(item.evidential_relevance.cannot_establish)
        ],
        why=(
            scrub(item.evidential_relevance.why, "evidential_relevance.why")
            if item.evidential_relevance.why
            else None
        ),
    )

    alias: SourceAlias | None = None
    if active.pseudonymise_sources:
        source_ref, alias_id = _pseudonymous_source(item.source_ref, vocabulary)
        alias = SourceAlias(
            real_source_id=item.source_ref.id,
            alias_source_id=alias_id,
            real_publisher=item.source_ref.publisher,
            evidence_ids=(item.id,),
        )
    else:
        source_ref = item.source_ref

    blinded = item.model_copy(
        deep=True,
        update={
            "source_ref": source_ref,
            "statement": statement,
            "spans": spans,
            "evidential_relevance": relevance,
            "notes": scrub(item.notes, "notes") if item.notes else None,
        },
    )
    return blinded, tuple(collected), alias


# ---------------------------------------------------------------------------
# Interpretability — the over-redaction boundary
# ---------------------------------------------------------------------------


def assess_interpretability(
    original: str,
    redacted: str,
    *,
    policy: RedactionPolicy | None = None,
) -> InterpretabilityReport:
    """Judge whether a redacted claim still carries enough to be evaluated.

    Three failure signatures, each a real way redaction goes wrong:

    * **Placeholder saturation.** When more than
      :attr:`RedactionPolicy.max_placeholder_density` of the characters are
      placeholders, the sentence has become a template. Whatever verdict comes
      back is about the template.
    * **Content collapse.** Fewer than
      :attr:`RedactionPolicy.min_remaining_content_words` real words means there
      is no proposition left, only a frame.
    * **Lost quantities.** Any number present before and absent after is a
      redactor bug, full stop. Numbers are never identity, they are the most
      checkable thing a claim contains, and losing one silently converts an
      arithmetically testable claim into an unverifiable one.

    Returns a report rather than raising, so a caller can log a warning during
    exploration and fail a build in CI. :func:`blind_claim` raises when
    ``strict_interpretability`` is set.
    """
    active = policy or RedactionPolicy()
    reasons: list[str] = []

    placeholder_chars = sum(len(m.group(0)) for m in _PLACEHOLDER_RE.finditer(redacted))
    density = placeholder_chars / len(redacted) if redacted else 1.0
    if density > active.max_placeholder_density:
        reasons.append(
            f"placeholders make up {density:.0%} of the redacted claim, above the "
            f"{active.max_placeholder_density:.0%} ceiling: what remains is a template, "
            "not a proposition"
        )

    without_placeholders = _PLACEHOLDER_RE.sub(" ", redacted)
    content_words = list(_WORD_RE.findall(without_placeholders))
    if len(content_words) < active.min_remaining_content_words:
        reasons.append(
            f"only {len(content_words)} content word(s) survive redaction, below the "
            f"minimum of {active.min_remaining_content_words}: the claim can no longer "
            "be read, so any verdict would describe the redaction rather than the claim"
        )

    original_numbers = _NUMBER_RE.findall(original)
    redacted_numbers = _NUMBER_RE.findall(redacted)
    numbers_preserved = sorted(original_numbers) == sorted(redacted_numbers)
    if not numbers_preserved:
        lost = sorted(set(original_numbers) - set(redacted_numbers))
        reasons.append(
            f"quantities were lost in redaction ({', '.join(lost) or 'unknown'}): numbers "
            "are never identity and removing one turns a checkable claim into an "
            "unverifiable one"
        )

    return InterpretabilityReport(
        interpretable=not reasons,
        placeholder_density=density,
        remaining_content_words=len(content_words),
        numbers_preserved=numbers_preserved,
        reasons=tuple(reasons),
    )


# ---------------------------------------------------------------------------
# Leak verification
# ---------------------------------------------------------------------------


def _iter_context_strings(ctx: RedactedClaimContext) -> list[tuple[str, str]]:
    """Yield every ``(field_path, text)`` pair reachable from a blind context."""
    out: list[tuple[str, str]] = [("claim_text", ctx.claim_text)]
    for i, excerpt in enumerate(ctx.context_excerpts):
        out.append((f"context_excerpts[{i}]", excerpt))
    for i, item in enumerate(ctx.evidence):
        base = f"evidence[{i}]"
        out.append((f"{base}.statement", item.statement))
        out.append((f"{base}.source_ref.title", item.source_ref.title))
        if item.source_ref.publisher:
            out.append((f"{base}.source_ref.publisher", item.source_ref.publisher))
        if item.source_ref.url:
            out.append((f"{base}.source_ref.url", item.source_ref.url))
        out.append((f"{base}.source_ref.id", item.source_ref.id))
        for j, span in enumerate(item.spans):
            out.append((f"{base}.spans[{j}].text", span.text))
        out.append((f"{base}.evidential_relevance.question", item.evidential_relevance.question))
        if item.evidential_relevance.why:
            out.append((f"{base}.evidential_relevance.why", item.evidential_relevance.why))
        for j, entry in enumerate(item.evidential_relevance.can_establish):
            out.append((f"{base}.evidential_relevance.can_establish[{j}]", entry))
        for j, entry in enumerate(item.evidential_relevance.cannot_establish):
            out.append((f"{base}.evidential_relevance.cannot_establish[{j}]", entry))
        if item.notes:
            out.append((f"{base}.notes", item.notes))
        for j, uncertainty in enumerate(item.uncertainties):
            out.append((f"{base}.uncertainties[{j}].statement", uncertainty.statement))
    return out


def leak_report(
    ctx: RedactedClaimContext,
    known_identities: IdentityVocabulary | Iterable[str],
) -> LeakReport:
    """Scan a blind context for identities that should not have survived.

    Matching is accent- and case-insensitive and bounded by word edges, so
    "Sánchez", "sanchez" and "SANCHEZ" are all caught, while a term that merely
    occurs as a substring of an unrelated word is not. Terms shorter than three
    characters are skipped: an initial or a two-letter abbreviation produces
    constant false positives and would train reviewers to ignore the report,
    which is worse than the leak it would occasionally catch.

    This is the diagnostic form. Use :func:`assert_no_identity_leak` where a
    surviving identity must stop the pipeline.
    """
    terms = (
        known_identities.all_terms()
        if isinstance(known_identities, IdentityVocabulary)
        else frozenset(t for t in known_identities if t and t.strip())
    )
    checkable = [t.strip() for t in terms if len(t.strip()) >= 3]
    fields = _iter_context_strings(ctx)
    hits: list[LeakHit] = []
    for term in sorted(checkable, key=lambda t: (-len(t), t)):
        pattern = re.compile(rf"\b{_accent_flexible(term)}\b", re.IGNORECASE | re.UNICODE)
        for path, value in fields:
            for match in pattern.finditer(value):
                start = max(0, match.start() - 40)
                end = min(len(value), match.end() + 40)
                hits.append(
                    LeakHit(
                        term=term,
                        field_path=path,
                        char_start=match.start(),
                        char_end=match.end(),
                        excerpt=value[start:end],
                    )
                )
    return LeakReport(hits=tuple(hits), fields_scanned=len(fields), terms_checked=len(checkable))


def assert_no_identity_leak(
    ctx: RedactedClaimContext,
    known_identities: IdentityVocabulary | Iterable[str],
    *,
    claim_id: str | None = None,
) -> None:
    """Raise unless the blind context is free of every known identity.

    This is the assertion that turns Aleph's blindness from a design intention
    into a checked property. It is cheap, it is meant to run on every claim in
    production rather than only in tests, and a failure is a defect in Aleph
    itself — not a data problem and not something to downgrade to a warning.

    Raises:
        NeutralityViolationError: With the offending terms and their locations in
            ``context``, so the leak can be found without re-running anything.
    """
    report = leak_report(ctx, known_identities)
    if report.clean:
        return
    leaked = sorted({hit.term for hit in report.hits})
    raise NeutralityViolationError(
        "identity survived redaction and reached the blind factual evaluator; the "
        "verdict path is only speaker-blind if this never happens",
        claim_id=claim_id,
        perturbation="redaction_leak_check",
        leaked_terms=leaked,
        locations=[hit.field_path for hit in report.hits],
        redaction_version=ctx.redaction_version,
    )


# ---------------------------------------------------------------------------
# The main entry point
# ---------------------------------------------------------------------------


def blind_claim(
    claim: ClaimLike,
    evidence: Sequence[EvidenceItem] = (),
    *,
    vocabulary: IdentityVocabulary | None = None,
    context_excerpts: Sequence[str] = (),
    policy: RedactionPolicy | None = None,
    attribution_at_issue: AttributionAtIssue | None = None,
    verify: bool = True,
    claim_id: str | None = None,
) -> Blinding:
    """Convert a claim and its evidence into the only object the evaluator may see.

    The result is a :class:`~aleph.core.models.RedactedClaimContext` — frozen,
    closed, and with no field a speaker could be written into — carrying claim
    text, date, semantic context and evidence, and nothing else. Everything
    identity-bearing on the source claim (provenance, article, cluster, any
    attributed analysis) is dropped structurally by the context type; this
    function additionally scrubs identity out of the *prose*, which is where the
    type cannot reach.

    Args:
        claim: Anything satisfying :class:`ClaimLike`. Only ``normalised_text``
            and ``made_at`` are read; a ``context_excerpts`` attribute is used if
            present.
        evidence: Items to show the evaluator, in presentation order. Order must
            not change a verdict — the ``evidence_order_shuffle`` perturbation
            checks that — but it is preserved so the record is reproducible.
        vocabulary: Identities to strip, normally discovered from the corpus.
            An empty vocabulary still strips honorifics, alignment terms and the
            attributive frame, and still pseudonymises sources.
        context_excerpts: Interpretive context (a definition, the comparison
            class, the sentence a pronoun refers to). Redacted like the claim.
            This is the material that keeps redaction from destroying meaning, so
            supplying it generously is the antidote to over-redaction.
        policy: Redaction policy. Defaults to the strict one.
        attribution_at_issue: The deliberate escape hatch, for claims whose
            subject is itself an identity. Never populated by default.
        verify: Run the leak check and raise on failure. Leave on.
        claim_id: Recorded in any raised error.

    Returns:
        A :class:`Blinding` holding the context and the full audit trail.

    Raises:
        NeutralityViolationError: If ``verify`` is set and an identity survived.
        ValueError: If ``policy.strict_interpretability`` is set and redaction
            left the claim unevaluable. Failing here is deliberate: the
            alternative is an ``unverifiable`` verdict that reads as a finding
            about the world.
    """
    active = policy or RedactionPolicy()
    vocab = vocabulary or IdentityVocabulary()
    pseudonyms: dict[str, str] | None = None
    version = active.redaction_version
    if attribution_at_issue is not None:
        pseudonyms = dict(attribution_at_issue.pseudonyms())
        version = f"{version}{ATTRIBUTION_AT_ISSUE_SUFFIX}"

    original_text = claim.normalised_text
    claim_outcome = redact_text(
        original_text,
        vocab,
        policy=active,
        field_path="claim_text",
        pseudonyms=pseudonyms,
    )

    supplied_excerpts = list(context_excerpts) or list(getattr(claim, "context_excerpts", ()) or ())
    excerpt_outcomes = [
        redact_text(
            excerpt,
            vocab,
            policy=active,
            field_path=f"context_excerpts[{i}]",
            pseudonyms=pseudonyms,
        )
        for i, excerpt in enumerate(supplied_excerpts)
    ]
    excerpts = [outcome.text for outcome in excerpt_outcomes if outcome.text.strip()]

    if attribution_at_issue is not None:
        # Identity-free by construction: it names no one, and it tells the
        # evaluator how to read the pseudonyms it is about to encounter.
        excerpts.insert(
            0,
            "Attribution is the question at issue for this claim. The parties involved are "
            "referred to by stable pseudonyms ([SUBJECT_1], [SUBJECT_2], …) which denote the "
            "same party consistently across the claim and the evidence. Who they are is not "
            "part of this evaluation and is not supplied.",
        )

    blinded_evidence: list[EvidenceItem] = []
    evidence_replacements: list[Replacement] = []
    aliases: dict[str, SourceAlias] = {}
    for index, item in enumerate(evidence):
        blinded_item, item_replacements, alias = redact_evidence_item(
            item, vocab, policy=active, index=index, pseudonyms=pseudonyms
        )
        blinded_evidence.append(blinded_item)
        evidence_replacements.extend(item_replacements)
        if alias is not None:
            existing = aliases.get(alias.real_source_id)
            aliases[alias.real_source_id] = (
                SourceAlias(
                    real_source_id=alias.real_source_id,
                    alias_source_id=alias.alias_source_id,
                    real_publisher=alias.real_publisher,
                    evidence_ids=existing.evidence_ids + alias.evidence_ids,
                )
                if existing
                else alias
            )

    context = RedactedClaimContext(
        claim_text=claim_outcome.text or original_text,
        made_at=claim.made_at,
        context_excerpts=tuple(excerpts),
        evidence=tuple(blinded_evidence),
        withheld=tuple(active.withheld),
        redaction_version=version,
    )

    interpretability = assess_interpretability(original_text, context.claim_text, policy=active)
    if active.strict_interpretability and interpretability.over_redacted:
        raise ValueError(
            "redaction left the claim uninterpretable: "
            + "; ".join(interpretability.reasons)
            + ". Over-redaction is a defect, not a safe default: an unreadable claim "
            "produces an 'unverifiable' verdict that a reader will mistake for a "
            "finding about the world."
        )

    leaks = leak_report(context, vocab)
    if verify and not leaks.clean:
        assert_no_identity_leak(context, vocab, claim_id=claim_id)

    all_replacements = tuple(claim_outcome.replacements)
    for outcome in excerpt_outcomes:
        all_replacements += outcome.replacements
    all_replacements += tuple(evidence_replacements)

    preserved = tuple(
        dict.fromkeys(
            list(claim_outcome.preserved_hits)
            + [hit for outcome in excerpt_outcomes for hit in outcome.preserved_hits]
        )
    )

    return Blinding(
        context=context,
        replacements=all_replacements,
        interpretability=interpretability,
        leaks=leaks,
        source_aliases=tuple(aliases.values()),
        attribution_at_issue=attribution_at_issue,
        preserved_hits=preserved,
    )


def redact_claim(
    claim: ClaimLike,
    evidence: Sequence[EvidenceItem] = (),
    *,
    vocabulary: IdentityVocabulary | None = None,
    context_excerpts: Sequence[str] = (),
    policy: RedactionPolicy | None = None,
    attribution_at_issue: AttributionAtIssue | None = None,
) -> RedactedClaimContext:
    """Return just the blind context, discarding the diagnostics.

    Convenience over :func:`blind_claim` for callers that only need the object to
    hand to the evaluator. Verification still runs, so a leak still raises.
    """
    return blind_claim(
        claim,
        evidence,
        vocabulary=vocabulary,
        context_excerpts=context_excerpts,
        policy=policy,
        attribution_at_issue=attribution_at_issue,
    ).context


def withheld_for(categories: Iterable[IdentityCategory]) -> tuple[WithheldCategory, ...]:
    """Map internal redaction categories onto the published withheld vocabulary.

    Used when a caller narrows :attr:`RedactionPolicy.categories` and needs the
    audit record to state accurately what was and was not removed. A record that
    over-claims what it withheld is worse than one that admits a narrower scope.
    """
    out = [
        _CATEGORY_TO_WITHHELD[category]
        for category in categories
        if category in _CATEGORY_TO_WITHHELD
    ]
    return tuple(dict.fromkeys(out))


@dataclass(frozen=True)
class BlindingBatch:
    """Blindings for several claims, with the aggregate leak position.

    ``all_clean`` is the number a neutrality gate reads: one leak anywhere in a
    bundle means the bundle's verdicts were not all produced blind.
    """

    blindings: tuple[Blinding, ...] = ()
    aliases: tuple[SourceAlias, ...] = field(default_factory=tuple)

    @property
    def all_clean(self) -> bool:
        """True when no blinding in the batch leaked an identity."""
        return all(blinding.leaks.clean for blinding in self.blindings)

    @property
    def over_redacted_count(self) -> int:
        """How many claims were reduced past the point of being evaluable."""
        return sum(1 for b in self.blindings if b.interpretability.over_redacted)
