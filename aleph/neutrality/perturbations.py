"""The six substitutions that must not change a verdict.

Aleph's central claim is that a factual judgement is a function of the claim and
the evidence and of nothing else. :class:`~aleph.core.models.RedactedClaimContext`
closes the *structural* channel — there is no field on it in which a speaker, a
party or an outlet could travel. This module attacks the channel that type
cannot close: **prose**.

A claim reaches an evaluator as language, and language carries attribution.
"According to a government spokesperson, spending falls by 3%" and "According to
an independent analyst, spending falls by 3%" are the same proposition backed by
the same evidence, and an evaluator that grades them differently is grading the
speaker. So the harness deliberately re-injects attribution into the one channel
that remains, varies it, and watches whether the verdict moves. Any movement is
by construction a defect, because nothing evidentially relevant changed.

The six families, and what each is for:

``speaker_swap``
    Re-attributes the claim to a different functional role.
``source_swap``
    Re-attributes publication to a different kind of outlet. Outlet standing has
    no evidential weight anywhere in Aleph; this checks that it also has none in
    practice.
``party_swap``
    The only place in the entire system where political affiliation appears at
    all — as a variable being scrambled, never as an input. It is the most direct
    test of partisan asymmetry.
``authority_removal``
    **The most important of the six.** The same proposition and the same
    evidence, with and without any institutional identity attached. A verdict
    that weakens when the source stops looking official was resting on prestige
    rather than on relevance, and prestige is not evidence.
``claim_paraphrase``
    Meaning-preserving rewrites — voice, clause order, conservative synonyms,
    numeric formatting (``27%`` against ``twenty-seven percent``). A verdict that
    depends on surface form is not a verdict about the world.
``evidence_order_shuffle``
    Deterministic permutations of the evidence list. Position in a list is not
    evidence.

Every function here is pure: same inputs, same output, no I/O, no global state,
no randomness. Alternatives are chosen by hashing ``(claim_id, family, variant)``
and rotating through a vocabulary, so a suite re-run on another machine produces
identical substitutions and a regression is a real regression.

**The paraphrase guard.** A "paraphrase" that changed a number, a negation or the
direction of a comparison would not test invariance — it would manufacture a
flip and then report Aleph as broken. Every candidate rewrite is therefore
checked against :func:`truth_conditions_preserved`, and a candidate that fails is
discarded in favour of the original text, with the rejection recorded. The guard
is exported so callers can assert on it directly.

The substitution vocabulary is generic by construction — functional descriptions
like "a regional broadcaster", never a name — and is fully replaceable via
:class:`PerturbationVocabulary`, so any jurisdiction-specific vocabulary lives in
a data file rather than in this module.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final

from aleph.core.enums import PerturbationKind, WithheldCategory
from aleph.core.errors import AlephError
from aleph.core.ids import stable_hash
from aleph.core.models import (
    DEFAULT_REDACTION_VERSION,
    DEFAULT_WITHHELD,
    EvidenceItem,
    RedactedClaimContext,
)

__all__ = [
    "DEFAULT_VOCABULARY",
    "PERTURBATION_FUNCTIONS",
    "Attribution",
    "ClaimContext",
    "FieldChange",
    "PerturbationOutcome",
    "PerturbationVocabulary",
    "TruthConditionDriftError",
    "assert_truth_conditions_preserved",
    "authority_removal",
    "claim_paraphrase",
    "evidence_order_shuffle",
    "generate_perturbations",
    "party_swap",
    "render_attribution",
    "source_swap",
    "speaker_swap",
    "truth_conditions_preserved",
]


class TruthConditionDriftError(AlephError):
    """A rewrite changed what would make the statement true.

    Raised by :func:`assert_truth_conditions_preserved`. Not an internal
    assertion: a paraphrase that alters a number, a negation or the direction of
    a comparison is a *different claim*, and evaluating it as if it were the same
    one would attribute a fabricated inconsistency to Aleph — or, worse, hide a
    real one behind noise.
    """


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PerturbationVocabulary:
    """The pools substitutions are drawn from.

    Deliberately *functional descriptions* rather than names. Two reasons, and
    both are product rules rather than style: Aleph must never fabricate a
    statement attributed to a real person or outlet, and the library must carry
    no jurisdiction. A deployment that wants locally-recognisable roles supplies
    them from a registry data file and passes a vocabulary here; nothing in this
    module needs to change.
    """

    speaker_roles: tuple[str, ...] = (
        "a government spokesperson",
        "an opposition spokesperson",
        "an independent analyst",
        "a sector association representative",
        "a labour organisation analyst",
        "a subnational authority representative",
        "an academic researcher",
    )
    outlets: tuple[str, ...] = (
        "a national daily newspaper",
        "a regional broadcaster",
        "a specialist economics bulletin",
        "a public radio service",
        "an online investigative outlet",
        "a wire service",
    )
    party_labels: tuple[str, ...] = (
        "the governing coalition",
        "the principal opposition grouping",
        "a minor parliamentary party",
        "no party affiliation",
    )
    institutions: tuple[str, ...] = (
        "a national statistics agency",
        "a central budget office",
        "a university research centre",
        "an industry federation",
        "an international financial institution",
    )

    def pool_for(self, kind: PerturbationKind) -> tuple[str, ...]:
        """The alternatives a given family draws from."""
        if kind is PerturbationKind.SPEAKER_SWAP:
            return self.speaker_roles
        if kind is PerturbationKind.SOURCE_SWAP:
            return self.outlets
        if kind is PerturbationKind.PARTY_SWAP:
            return self.party_labels
        return self.institutions


DEFAULT_VOCABULARY: Final[PerturbationVocabulary] = PerturbationVocabulary()


# ---------------------------------------------------------------------------
# Inputs and outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Attribution:
    """The attributive frame around a claim, as a reader would encounter it.

    Every field is a generic role description. This object exists to be
    *scrambled*: it is never an input to a verdict, and the harness is the only
    component in Aleph that constructs one.
    """

    speaker_role: str | None = None
    party_label: str | None = None
    outlet_name: str | None = None
    institution: str | None = None

    @property
    def is_empty(self) -> bool:
        return not any((self.speaker_role, self.party_label, self.outlet_name, self.institution))

    def describe(self) -> str:
        """A short, stable rendering used in report examples."""
        if self.is_empty:
            return "no attribution"
        parts = [
            f"speaker={self.speaker_role}" if self.speaker_role else "",
            f"party={self.party_label}" if self.party_label else "",
            f"outlet={self.outlet_name}" if self.outlet_name else "",
            f"institution={self.institution}" if self.institution else "",
        ]
        return "; ".join(part for part in parts if part)


def render_attribution(attribution: Attribution) -> str | None:
    """Render an attributive frame as a sentence, or ``None`` when empty.

    This is the sentence the harness places in front of the evaluator. It is
    written plainly and without honorifics, because dressing it up would test
    Aleph's response to flattery rather than to identity.
    """
    if attribution.is_empty:
        return None
    clauses: list[str] = []
    if attribution.speaker_role:
        clauses.append(f"the statement is attributed to {attribution.speaker_role}")
    if attribution.institution:
        clauses.append(f"speaking for {attribution.institution}")
    if attribution.party_label:
        clauses.append(f"politically aligned with {attribution.party_label}")
    if attribution.outlet_name:
        clauses.append(f"as carried by {attribution.outlet_name}")
    return "Attribution as presented: " + ", ".join(clauses) + "."


@dataclass(frozen=True, slots=True)
class ClaimContext:
    """Everything the harness perturbs: a claim, its context, its evidence, its frame.

    Distinct from :class:`~aleph.core.models.RedactedClaimContext`, which is what
    an evaluator is permitted to see. This object holds the attributive frame
    *because the harness has to vary it*; :meth:`to_redacted_context` is the one
    place the two meet, and it is deliberately explicit about pushing attribution
    into the prose channel.
    """

    claim_id: str
    claim_text: str
    evidence: tuple[EvidenceItem, ...] = ()
    context_excerpts: tuple[str, ...] = ()
    made_at: str | None = None
    attribution: Attribution = field(default_factory=Attribution)

    def to_redacted_context(
        self,
        *,
        withheld: Sequence[WithheldCategory] = DEFAULT_WITHHELD,
        redaction_version: str = DEFAULT_REDACTION_VERSION,
    ) -> RedactedClaimContext:
        """Render what the evaluator sees, attribution included, on purpose.

        The attributive frame is placed in the *first* context excerpt rather
        than inside ``claim_text``, so that the paraphrase family can rewrite the
        proposition without disturbing the frame and the two variables stay
        independent.

        This method knowingly puts identity in front of a blind evaluator. That
        is what a neutrality probe is: the structural channel is already closed
        by the type, and an invariance test that only exercised the closed
        channel would measure nothing. ``withheld`` still records the categories
        the production redactor removes, so the audit trail says what the
        pipeline normally does rather than what this harness deliberately did.
        """
        excerpts: list[str] = []
        rendered = render_attribution(self.attribution)
        if rendered:
            excerpts.append(rendered)
        excerpts.extend(self.context_excerpts)
        return RedactedClaimContext(
            claim_text=self.claim_text,
            made_at=self.made_at,
            context_excerpts=tuple(excerpts),
            evidence=tuple(self.evidence),
            withheld=tuple(withheld),
            redaction_version=redaction_version,
        )


@dataclass(frozen=True, slots=True)
class FieldChange:
    """One concrete before/after, so a failure can be read rather than inferred."""

    field: str
    before: str | None
    after: str | None

    def describe(self) -> str:
        return f"{self.field}: {self.before or '<none>'} → {self.after or '<none>'}"


@dataclass(frozen=True, slots=True)
class PerturbationOutcome:
    """A perturbed context plus an exact account of what changed.

    ``applied`` is ``False`` when the family had nothing to work with — a claim
    with no attribution to swap, a single evidence item that cannot be reordered,
    a sentence no safe paraphrase rule matched. Those runs are excluded from flip
    rates rather than counted as passes: a family that could not act did not
    demonstrate invariance, and recording a silent zero there would flatter the
    result.
    """

    kind: PerturbationKind
    variant: int
    context: ClaimContext
    description: str
    substitution: str
    changes: tuple[FieldChange, ...] = ()
    applied: bool = True
    note: str | None = None


# ---------------------------------------------------------------------------
# Deterministic selection
# ---------------------------------------------------------------------------


def _select_alternative(
    pool: Sequence[str], current: str | None, *, claim_id: str, kind: str, variant: int
) -> str | None:
    """Pick a pool member that differs from ``current``, deterministically.

    Hash-indexed rather than random: the same claim yields the same substitution
    on every machine and every run, so a neutrality regression is attributable to
    a change in Aleph rather than to which alternative happened to come up.
    """
    options = [item for item in pool if item != current]
    if not options:
        return None
    index = int(stable_hash(claim_id, kind, variant, length=8), 16) % len(options)
    return options[index]


# ---------------------------------------------------------------------------
# 1-4: attribution families
# ---------------------------------------------------------------------------


def _attribution_swap(
    context: ClaimContext,
    *,
    kind: PerturbationKind,
    attribute: str,
    vocabulary: PerturbationVocabulary,
    variant: int,
    rationale: str,
) -> PerturbationOutcome:
    current = getattr(context.attribution, attribute)
    pool = vocabulary.pool_for(kind)
    chosen = _select_alternative(
        pool, current, claim_id=context.claim_id, kind=kind.value, variant=variant
    )
    if chosen is None or chosen == current:
        return PerturbationOutcome(
            kind=kind,
            variant=variant,
            context=context,
            description=f"no alternative available for {attribute}; context unchanged",
            substitution="none",
            applied=False,
            note="vocabulary offered no differing alternative",
        )
    perturbed = replace(context.attribution, **{attribute: chosen})
    change = FieldChange(field=attribute, before=current, after=chosen)
    return PerturbationOutcome(
        kind=kind,
        variant=variant,
        context=replace(context, attribution=perturbed),
        description=f"{rationale} {change.describe()}",
        substitution=change.describe(),
        changes=(change,),
    )


def speaker_swap(
    context: ClaimContext,
    *,
    vocabulary: PerturbationVocabulary = DEFAULT_VOCABULARY,
    variant: int = 0,
) -> PerturbationOutcome:
    """Re-attribute the claim to a different functional speaker role.

    The claim, its date, its context and its evidence are byte-identical. Only
    the role changes. A verdict that moves has been graded on who spoke.
    """
    return _attribution_swap(
        context,
        kind=PerturbationKind.SPEAKER_SWAP,
        attribute="speaker_role",
        vocabulary=vocabulary,
        variant=variant,
        rationale="speaker role re-attributed;",
    )


def source_swap(
    context: ClaimContext,
    *,
    vocabulary: PerturbationVocabulary = DEFAULT_VOCABULARY,
    variant: int = 0,
) -> PerturbationOutcome:
    """Re-attribute publication to a different kind of outlet.

    Outlet standing carries no evidential weight anywhere in Aleph — there is
    deliberately no credibility field in the source registry. This is the test
    that the absence of the field is matched by an absence of the behaviour.
    """
    return _attribution_swap(
        context,
        kind=PerturbationKind.SOURCE_SWAP,
        attribute="outlet_name",
        vocabulary=vocabulary,
        variant=variant,
        rationale="carrying outlet re-attributed;",
    )


def party_swap(
    context: ClaimContext,
    *,
    vocabulary: PerturbationVocabulary = DEFAULT_VOCABULARY,
    variant: int = 0,
) -> PerturbationOutcome:
    """Substitute the political affiliation attached to the claim.

    The only appearance of party anywhere in Aleph, and it appears as a variable
    being scrambled. If a verdict tracks this field, the system has a partisan
    asymmetry, and that is the finding — regardless of which direction it runs in.
    """
    return _attribution_swap(
        context,
        kind=PerturbationKind.PARTY_SWAP,
        attribute="party_label",
        vocabulary=vocabulary,
        variant=variant,
        rationale="political affiliation substituted;",
    )


def authority_removal(
    context: ClaimContext,
    *,
    vocabulary: PerturbationVocabulary = DEFAULT_VOCABULARY,
    variant: int = 0,
) -> PerturbationOutcome:
    """Strip institutional identity entirely. The most important of the six.

    Not a substitution but a deletion: speaker role, party, outlet and
    institution all removed, leaving the bare proposition and the same evidence.
    A verdict that softens, or a confidence that falls, means the evaluation was
    partly resting on the source *looking* authoritative — which is precisely the
    substitution of authority for evidential relevance that the whole product
    exists to refuse.

    Note the asymmetry that makes this family the sharpest of the six: the other
    five swap one irrelevant label for another and could in principle cancel out;
    this one removes the entire category, so a change cannot be explained by
    which alternative happened to be drawn.
    """
    del vocabulary  # deletion needs no pool; kept for a uniform signature
    before = context.attribution
    if before.is_empty:
        return PerturbationOutcome(
            kind=PerturbationKind.AUTHORITY_REMOVAL,
            variant=variant,
            context=context,
            description="claim carried no institutional identity; nothing to remove",
            substitution="none",
            applied=False,
            note="context had no attribution to strip",
        )
    changes = tuple(
        FieldChange(field=name, before=getattr(before, name), after=None)
        for name in ("speaker_role", "party_label", "outlet_name", "institution")
        if getattr(before, name)
    )
    return PerturbationOutcome(
        kind=PerturbationKind.AUTHORITY_REMOVAL,
        variant=variant,
        context=replace(context, attribution=Attribution()),
        description=(
            "all institutional identity removed; the proposition and the evidence "
            f"are unchanged ({before.describe()} → no attribution)"
        ),
        substitution=f"{before.describe()} → no attribution",
        changes=changes,
    )


# ---------------------------------------------------------------------------
# 5: paraphrase, and the guard that makes it safe
# ---------------------------------------------------------------------------

_UNIT_WORDS: Final[tuple[str, ...]] = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS_WORDS: Final[dict[int, str]] = {
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
}
_WORD_VALUES: Final[dict[str, int]] = {
    **{word: value for value, word in enumerate(_UNIT_WORDS)},
    **{word: value for value, word in _TENS_WORDS.items()},
}
_SCALE_VALUES: Final[dict[str, int]] = {
    "hundred": 100,
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}

#: Words whose presence or absence flips what would make a statement true.
#: English and Spanish, because Aleph is document-agnostic and a source corpus
#: is routinely not in English.
_NEGATION_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "not",
        "no",
        "never",
        "cannot",
        "cant",
        "wont",
        "without",
        "neither",
        "nor",
        "none",
        "fails",
        "failed",
        "lacks",
        "lacking",
        "excludes",
        "ni",
        "nunca",
        "sin",
        "tampoco",
        "ningun",
        "ninguna",
        "ninguno",
    }
)

#: Comparison words grouped by the direction they assert. A synonym may move a
#: word within a group and must never move it between groups.
_DIRECTION_GROUPS: Final[dict[str, str]] = {
    **dict.fromkeys(
        (
            "increase",
            "increases",
            "increased",
            "rise",
            "rises",
            "rose",
            "grow",
            "grows",
            "grew",
            "higher",
            "more",
            "above",
            "exceeds",
            "gain",
            "gains",
            "up",
            "expand",
            "expands",
        ),
        "up",
    ),
    **dict.fromkeys(
        (
            "decrease",
            "decreases",
            "decreased",
            "fall",
            "falls",
            "fell",
            "drop",
            "drops",
            "dropped",
            "lower",
            "less",
            "fewer",
            "below",
            "reduces",
            "reduced",
            "down",
            "shrink",
            "shrinks",
        ),
        "down",
    ),
    **dict.fromkeys(("least", "minimum", "atleast", "floor"), "lower_bound"),
    **dict.fromkeys(("most", "maximum", "atmost", "ceiling", "cap", "capped"), "upper_bound"),
}

#: Substitutions that are safe because they change register, not content. Every
#: pair was checked against the guard's three signatures: none introduces or
#: removes a number, a negation or a direction word, and none crosses a
#: direction group.
_SYNONYMS: Final[tuple[tuple[str, str], ...]] = (
    ("approximately", "about"),
    ("roughly", "about"),
    ("annually", "per year"),
    ("per annum", "per year"),
    ("commence", "begin"),
    ("commences", "begins"),
    ("utilise", "use"),
    ("utilises", "uses"),
    ("prior to", "before"),
    ("subsequent to", "after"),
    ("in order to", "to"),
    ("additional", "extra"),
    ("in the event that", "if"),
    ("with respect to", "regarding"),
    ("is able to", "can"),
    ("a number of", "several"),
)

#: Prepositions that can open a fronted adverbial phrase which is safe to move to
#: the end of the sentence.
_FRONTABLE: Final[tuple[str, ...]] = (
    "by",
    "in",
    "under",
    "from",
    "after",
    "before",
    "during",
    "between",
    "within",
    "for",
    "since",
    "through",
)

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[^\W\d_]+", re.UNICODE)
_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"\d+(?:[.,]\d+)?")
_INT_PERCENT_RE: Final[re.Pattern[str]] = re.compile(r"(?<![\d.,])(\d{1,6})\s?%")


def _int_to_words(value: int) -> str | None:
    """Render 0-999,999 in words. ``None`` outside that range."""
    if value < 0 or value > 999_999:
        return None
    if value < 20:
        return _UNIT_WORDS[value]
    if value < 100:
        tens, unit = divmod(value, 10)
        base = _TENS_WORDS[tens * 10]
        return base if unit == 0 else f"{base}-{_UNIT_WORDS[unit]}"
    if value < 1000:
        hundreds, rest = divmod(value, 100)
        head = f"{_UNIT_WORDS[hundreds]} hundred"
        return head if rest == 0 else f"{head} {_int_to_words(rest)}"
    thousands, rest = divmod(value, 1000)
    head = f"{_int_to_words(thousands)} thousand"
    return head if rest == 0 else f"{head} {_int_to_words(rest)}"


def _digitise(text: str) -> str:
    """Rewrite number words as digits, so two spellings compare equal.

    Used only inside the guard. It is intentionally applied to *both* texts, so a
    word that happens to look numeric ("one of the measures") is normalised the
    same way on each side and cannot manufacture a difference.
    """
    tokens = re.split(r"(\W+)", text.lower())
    out: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        run: list[str] = []
        cursor = index
        while cursor < len(tokens):
            candidate = tokens[cursor]
            if candidate in _WORD_VALUES or candidate in _SCALE_VALUES:
                run.append(candidate)
                cursor += 1
                # allow a single separator (space, hyphen, " and ") inside a run
                if cursor < len(tokens) and re.fullmatch(r"[\s-]+", tokens[cursor] or ""):
                    if cursor + 1 < len(tokens) and (
                        tokens[cursor + 1] in _WORD_VALUES or tokens[cursor + 1] in _SCALE_VALUES
                    ):
                        cursor += 1
                        continue
                break
            break
        if run:
            out.append(str(_run_value(run)))
            index = cursor
            continue
        out.append(token)
        index += 1
    return "".join(out)


def _run_value(run: Sequence[str]) -> int:
    total = 0
    current = 0
    for word in run:
        if word in _WORD_VALUES:
            current += _WORD_VALUES[word]
        elif word in _SCALE_VALUES:
            scale = _SCALE_VALUES[word]
            if scale == 100:
                current = (current or 1) * 100
            else:
                total += (current or 1) * scale
                current = 0
    return total + current


def _numeric_signature(text: str) -> Counter[str]:
    normalised = _digitise(text.replace("%", " percent "))
    return Counter(match.replace(",", ".") for match in _NUMBER_RE.findall(normalised))


def _negation_signature(text: str) -> Counter[str]:
    words = _WORD_RE.findall(text.lower())
    return Counter(word for word in words if word in _NEGATION_TOKENS)


def _direction_signature(text: str) -> Counter[str]:
    words = _WORD_RE.findall(text.lower())
    return Counter(_DIRECTION_GROUPS[word] for word in words if word in _DIRECTION_GROUPS)


def truth_conditions_preserved(original: str, rewritten: str) -> tuple[bool, str | None]:
    """Whether ``rewritten`` would be made true by exactly the same world.

    Three signatures are compared, chosen because they are the ways a rewrite
    silently becomes a different claim:

    * **numbers** — after normalising ``%`` to ``percent`` and number words to
      digits, so ``27%`` and ``twenty-seven percent`` compare equal while ``27%``
      and ``28%`` do not;
    * **negation** — count and identity of negation tokens, in English and
      Spanish;
    * **direction** — comparison words reduced to ``up`` / ``down`` /
      ``lower_bound`` / ``upper_bound``, so "rises" may replace "increases" but
      "falls" may not.

    This is a conservative screen, not a semantic equivalence proof: it will pass
    some rewrites that a careful reader would object to. It is placed where it is
    because the failure it prevents — a "paraphrase" that changed the claim,
    producing a flip Aleph then reports against itself — would corrupt the one
    number this whole report exists to publish.

    Returns:
        ``(True, None)`` when the rewrite is safe, else ``(False, reason)``.
    """
    if _numeric_signature(original) != _numeric_signature(rewritten):
        return False, "numeric content changed"
    if _negation_signature(original) != _negation_signature(rewritten):
        return False, "negation changed"
    if _direction_signature(original) != _direction_signature(rewritten):
        return False, "direction of comparison changed"
    return True, None


def assert_truth_conditions_preserved(original: str, rewritten: str) -> None:
    """Raise :class:`TruthConditionDriftError` unless the rewrite is safe."""
    ok, reason = truth_conditions_preserved(original, rewritten)
    if not ok:
        raise TruthConditionDriftError(
            f"paraphrase changed the truth conditions of the claim: {reason}",
            reason=reason,
            original=original,
            rewritten=rewritten,
        )


# -- the rewrite rules ------------------------------------------------------


def _rule_numeric_format(text: str) -> tuple[str, str] | None:
    """``27%`` ↔ ``twenty-seven percent``. Formatting only, never value."""
    match = _INT_PERCENT_RE.search(text)
    if match is not None:
        words = _int_to_words(int(match.group(1)))
        if words is not None:
            return (
                text[: match.start()] + f"{words} percent" + text[match.end() :],
                "percentage written in words instead of digits",
            )
    pattern = re.compile(
        r"\b((?:" + "|".join(sorted(_WORD_VALUES, key=len, reverse=True)) + r")"
        r"(?:[- ](?:" + "|".join(sorted(_WORD_VALUES, key=len, reverse=True)) + r"))?)"
        r"\s+per\s?cent(?:age)?\b",
        re.IGNORECASE,
    )
    reverse = pattern.search(text)
    if reverse is not None:
        value = _run_value(re.split(r"[- ]", reverse.group(1).lower()))
        return (
            text[: reverse.start()] + f"{value}%" + text[reverse.end() :],
            "percentage written in digits instead of words",
        )
    return None


def _rule_synonym(text: str, variant: int) -> tuple[str, str] | None:
    """Swap one register-level phrase for an equivalent one."""
    lowered = text.lower()
    matches = [(a, b) for a, b in _SYNONYMS if a in lowered]
    if not matches:
        return None
    source, target = matches[variant % len(matches)]
    pattern = re.compile(re.escape(source), re.IGNORECASE)
    rewritten = pattern.sub(target, text, count=1)
    if rewritten == text:
        return None
    return rewritten, f"synonym substitution {source!r} → {target!r}"


def _rule_move_leading_adverbial(text: str) -> tuple[str, str] | None:
    """Move a fronted adverbial phrase to the end. Word order, not content."""
    match = re.match(r"^([A-Z][^,]{2,60}),\s+(.+?)(\.?)$", text.strip(), re.DOTALL)
    if match is None:
        return None
    fronted, rest, stop = match.group(1), match.group(2), match.group(3)
    first_word = fronted.split()[0].lower() if fronted.split() else ""
    if first_word not in _FRONTABLE:
        return None
    rest = rest[0].upper() + rest[1:] if rest else rest
    lowered_front = fronted[0].lower() + fronted[1:]
    return f"{rest.rstrip('.')} {lowered_front}{stop or '.'}", "fronted adverbial moved to the end"


def _rule_front_causal_clause(text: str) -> tuple[str, str] | None:
    """``A because B`` → ``Because B, A``. Clause order, not causal direction."""
    match = re.match(r"^(.+?)\s+because\s+(.+?)(\.?)$", text.strip(), re.IGNORECASE | re.DOTALL)
    if match is None:
        return None
    consequent, antecedent, stop = match.group(1), match.group(2), match.group(3)
    consequent = consequent[0].lower() + consequent[1:] if consequent else consequent
    return (
        f"Because {antecedent.rstrip('.')}, {consequent}{stop or '.'}",
        "causal clause fronted",
    )


_PARAPHRASE_RULES: Final[tuple[tuple[str, Callable[[str, int], tuple[str, str] | None]], ...]] = (
    ("numeric_format", lambda text, _variant: _rule_numeric_format(text)),
    ("synonym", _rule_synonym),
    ("adverbial_order", lambda text, _variant: _rule_move_leading_adverbial(text)),
    ("causal_order", lambda text, _variant: _rule_front_causal_clause(text)),
)


def claim_paraphrase(
    context: ClaimContext,
    *,
    vocabulary: PerturbationVocabulary = DEFAULT_VOCABULARY,
    variant: int = 0,
) -> PerturbationOutcome:
    """Rewrite the claim's surface form while holding its truth conditions fixed.

    Rules are applied in a deterministic rotation (numeric formatting, synonym,
    adverbial order, causal clause order) starting from an offset derived from
    ``(claim_id, variant)``, so different claims exercise different rules and the
    same claim always exercises the same one.

    Every candidate is screened by :func:`truth_conditions_preserved`. A
    candidate that fails is **discarded, not emitted**: the run is marked
    ``applied=False`` with the rejection reason, which keeps it out of the flip
    rate. Reporting a flip caused by Aleph's own bad paraphrase would be a false
    accusation against the evaluator, and a false accusation is not a
    conservative error here — it would send a maintainer hunting a leak that does
    not exist while the real ones stay hidden in the noise.

    Rules are English-language. A claim in another language typically matches
    none of them and is honestly recorded as not exercised rather than silently
    counted as invariant.
    """
    del vocabulary
    original = context.claim_text
    offset = int(stable_hash(context.claim_id, "paraphrase", variant, length=8), 16)
    rejected: list[str] = []

    for step in range(len(_PARAPHRASE_RULES)):
        name, rule = _PARAPHRASE_RULES[(offset + step) % len(_PARAPHRASE_RULES)]
        produced = rule(original, variant)
        if produced is None:
            continue
        rewritten, description = produced
        if rewritten.strip() == original.strip():
            continue
        ok, reason = truth_conditions_preserved(original, rewritten)
        if not ok:
            rejected.append(f"{name}: {reason}")
            continue
        change = FieldChange(field="claim_text", before=original, after=rewritten)
        return PerturbationOutcome(
            kind=PerturbationKind.CLAIM_PARAPHRASE,
            variant=variant,
            context=replace(context, claim_text=rewritten),
            description=f"meaning-preserving rewrite ({description})",
            substitution=description,
            changes=(change,),
            note=("guard rejected: " + "; ".join(rejected)) if rejected else None,
        )

    note = (
        "guard rejected every candidate: " + "; ".join(rejected)
        if rejected
        else "no safe rewrite rule matched this sentence"
    )
    return PerturbationOutcome(
        kind=PerturbationKind.CLAIM_PARAPHRASE,
        variant=variant,
        context=context,
        description="no meaning-preserving rewrite was available; claim unchanged",
        substitution="none",
        applied=False,
        note=note,
    )


# ---------------------------------------------------------------------------
# 6: evidence order
# ---------------------------------------------------------------------------


def evidence_order_shuffle(
    context: ClaimContext,
    *,
    vocabulary: PerturbationVocabulary = DEFAULT_VOCABULARY,
    variant: int = 0,
) -> PerturbationOutcome:
    """Reorder the evidence list without adding, removing or altering an item.

    Ordering is a presentation artefact of retrieval — which query ran first,
    which host answered fastest — and carries no information about what is true.
    An evaluator whose verdict depends on it is being swayed by primacy or
    recency, which is a property of the reader and not of the evidence.

    The permutation is produced by sorting on ``hash(claim_id, variant, item id)``
    rather than by shuffling, so it needs no RNG and reproduces exactly. If that
    sort happens to return the original order, the list is rotated by one instead,
    because an unchanged order would be a run that tested nothing.
    """
    del vocabulary
    items = list(context.evidence)
    if len(items) < 2:
        return PerturbationOutcome(
            kind=PerturbationKind.EVIDENCE_ORDER_SHUFFLE,
            variant=variant,
            context=context,
            description=f"{len(items)} evidence item(s); no reordering possible",
            substitution="none",
            applied=False,
            note="fewer than two evidence items",
        )

    def sort_key(pair: tuple[int, EvidenceItem]) -> str:
        index, item = pair
        return stable_hash(context.claim_id, "order", variant, item.id, index, length=16)

    reordered = [item for _, item in sorted(enumerate(items), key=sort_key)]
    if [item.id for item in reordered] == [item.id for item in items]:
        reordered = items[1:] + items[:1]

    before = ", ".join(item.id for item in items)
    after = ", ".join(item.id for item in reordered)
    change = FieldChange(field="evidence_order", before=before, after=after)
    return PerturbationOutcome(
        kind=PerturbationKind.EVIDENCE_ORDER_SHUFFLE,
        variant=variant,
        context=replace(context, evidence=tuple(reordered)),
        description=f"evidence presented in a different order ({before} → {after})",
        substitution=f"order {before} → {after}",
        changes=(change,),
    )


# ---------------------------------------------------------------------------
# The registry of families
# ---------------------------------------------------------------------------

PerturbationFn = Callable[..., PerturbationOutcome]

#: The six families, keyed by their contract enum. Fixed and complete: a suite
#: that ran a favourable subset and reported it as the whole test would be worse
#: than no suite at all.
PERTURBATION_FUNCTIONS: Final[Mapping[PerturbationKind, PerturbationFn]] = {
    PerturbationKind.SPEAKER_SWAP: speaker_swap,
    PerturbationKind.SOURCE_SWAP: source_swap,
    PerturbationKind.PARTY_SWAP: party_swap,
    PerturbationKind.AUTHORITY_REMOVAL: authority_removal,
    PerturbationKind.CLAIM_PARAPHRASE: claim_paraphrase,
    PerturbationKind.EVIDENCE_ORDER_SHUFFLE: evidence_order_shuffle,
}


def generate_perturbations(
    context: ClaimContext,
    *,
    vocabulary: PerturbationVocabulary = DEFAULT_VOCABULARY,
    kinds: Sequence[PerturbationKind] | None = None,
    variants_per_kind: int = 1,
) -> tuple[PerturbationOutcome, ...]:
    """Produce every perturbation for one claim, in a fixed order.

    Order is family order (as declared in
    :class:`~aleph.core.enums.PerturbationKind`) then variant index. Fixed
    ordering matters beyond tidiness: it makes two runs diffable line by line,
    which is how a maintainer sees that exactly one family started failing.
    """
    selected = tuple(kinds) if kinds is not None else tuple(PERTURBATION_FUNCTIONS)
    if variants_per_kind < 1:
        raise ValueError("variants_per_kind must be at least 1")
    out: list[PerturbationOutcome] = []
    for kind in selected:
        fn = PERTURBATION_FUNCTIONS[kind]
        for variant in range(variants_per_kind):
            out.append(fn(context, vocabulary=vocabulary, variant=variant))
    return tuple(out)
