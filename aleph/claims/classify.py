"""Deciding what *kind* of utterance a claim is, before anyone asks if it is true.

This module answers a question that has to be settled before evaluation begins:
is this statement the sort of thing that can be checked at all? A verifiable
assertion about what is or was, a defensible reading of facts, a prediction, a
preference, and a claim about what ought to be are five different objects. They
fail in different ways, they need different evidence, and only the first can be
graded true or false.

Getting this wrong is the most damaging error Aleph could make, and it is
damaging in a specific direction. A forecast presented to a reader as a checkable
fact is a promise that the future has been audited. An opinion graded
``unsupported`` looks like a refutation of something that was never offered as a
finding. Both mistakes read as rigour while being category errors, and both are
easy to commit silently — which is why the distinction is a first-class,
inspectable output here rather than a side effect of a prompt.

Three design commitments follow.

**The cues are data, not code.** Every linguistic signal lives in a module-level
tuple: modality, tense morphology, evaluative adjectives, conditionals, deontic
verbs, hedges and certainty markers, in Spanish and English. A reviewer who
disagrees with a classification can look up which cue fired and argue with the
cue, and adding a language means adding entries rather than editing logic.

**Every classification carries its evidence.** :class:`ClaimClassification`
returns the type *and* the :class:`CueHit` list that produced it, with the matched
substring and its offsets. A type with no cues is reported as such — it means the
sentence was a bare declarative and fell to the documented default.

**Ties resolve away from 'fact'.** When two types score equally the precedence in
:data:`TIE_BREAK_ORDER` prefers the classification that keeps the statement out
of the checkable-fact bucket. Calling a fact an interpretation costs a reader a
little precision; calling a forecast a fact tells them the future has been
verified.

Forecasts get one extra piece of work. A prediction is only evaluable against the
things it takes for granted, so :func:`detect_assumptions` recovers the stated
conditions and, where none are stated, names the structural ones the forecast
form itself implies — flagged ``is_explicit=False``, because "the speaker assumed
this" and "this assumption is inherent in making a projection at all" are
different claims about the speaker.

Nothing here reads a clock, a network or an environment variable, and nothing
here names a jurisdiction, an institution, a party or a person: the classifier
sees a string and returns a type. Identity plays no part in it, which is what
makes it safe to run on the blind side of the evaluation boundary.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from aleph.core.enums import AssumptionType, StatementType, TimeHorizon

__all__ = [
    "CLASSIFIER_VERSION",
    "Cue",
    "CueHit",
    "ForecastAssumption",
    "ClaimClassification",
    "ClassificationBatch",
    "classify_all",
    "CUE_FAMILIES",
    "TYPED_FAMILIES",
    "TIE_BREAK_ORDER",
    "FAMILY_CONTRIBUTIONS",
    "BASELINE_SCORES",
    "detect_language",
    "find_cues",
    "classify_claim_text",
    "classify_statement",
    "detect_assumptions",
    "detect_time_horizon",
    "is_quantitative",
]

#: Version of this classifier. Recorded by callers so a re-classification that
#: changes a statement type is attributable to a cue change rather than to noise.
CLASSIFIER_VERSION: Final[str] = "aleph-claim-classifier/1.0.0"


# ---------------------------------------------------------------------------
# Cue representation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Cue:
    """One linguistic signal that a statement is of a particular kind.

    A cue is deliberately a small, arguable object rather than a branch in a
    function. ``note`` states *why* the signal points where it does, so that a
    published classification can be defended or attacked on the substance of the
    linguistics rather than on the authority of the pipeline.

    Attributes:
        id: Stable identifier, appearing verbatim in :class:`CueHit`.
        pattern: Regular expression, matched case-insensitively against the
            claim text.
        language: BCP-47-ish tag, or ``'xx'`` for a signal that is not
            language-specific (a numeral, a date).
        weight: Contribution to the score of the family's statement type.
            Morphological rules carry less weight than explicit lexical markers
            because morphology is noisier.
        note: Plain-language justification.
        exclude: Surface forms that match the pattern but are not instances of
            the phenomenon — Spanish future-tense morphology in particular
            collides with ordinary adverbs, and listing the collisions is more
            honest than complicating the regex until nobody can read it.
    """

    id: str
    pattern: str
    language: str
    weight: float
    note: str
    exclude: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class CueHit:
    """One cue actually found in one claim, located in the text.

    Offsets are into the string that was classified, so an interface can
    underline exactly the words that drove the decision. That is the whole point
    of returning hits: a classification a reader cannot locate in the sentence is
    an assertion, not an analysis.
    """

    cue_id: str
    family: str
    matched_text: str
    char_start: int
    char_end: int
    language: str
    weight: float
    note: str

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping for diagnostics and UI display."""
        return {
            "cue_id": self.cue_id,
            "family": self.family,
            "matched_text": self.matched_text,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "language": self.language,
            "weight": self.weight,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Cue data — Spanish and English
#
# These tuples are the substance of the module. Everything below them is
# bookkeeping. They are grouped by "family"; the five families named in
# TYPED_FAMILIES map directly onto a StatementType, and the rest are modifiers
# that shift the balance or are recorded for downstream checks.
# ---------------------------------------------------------------------------

# Spanish synthetic future ("aumentará", "reducirán") is a strong forecast signal
# and has no English equivalent, but the suffixes collide with a handful of
# common adverbs and nouns. Listing the collisions keeps the rule readable.
_ES_FUTURE_FALSE_POSITIVES: Final[frozenset[str]] = frozenset(
    {
        "detras",
        "atras",
        "quizas",
        "ademas",
        "jamas",
        "compas",
        "veras",
        "demas",
        "apenas",
        "camara",
        "barras",
    }
)

FORECAST_CUES: Final[tuple[Cue, ...]] = (
    Cue(
        id="en.forecast.will",
        pattern=r"\b(?:will|shall)\s+(?:not\s+|never\s+)?[a-z]",
        language="en",
        weight=1.4,
        note="English predictive auxiliary: asserts a state of the world that has not occurred yet.",
    ),
    Cue(
        id="en.forecast.going_to",
        pattern=r"\b(?:is|are|am)\s+going\s+to\b",
        language="en",
        weight=1.2,
        note="Periphrastic future.",
    ),
    Cue(
        id="en.forecast.expected",
        pattern=r"\b(?:is|are)\s+(?:expected|projected|forecast|set|due|on\s+track)\s+to\b",
        language="en",
        weight=1.5,
        note="Explicit projection framing: the statement reports an expectation, not an observation.",
    ),
    Cue(
        id="en.forecast.projection_noun",
        pattern=r"\b(?:projection|projections|forecast|forecasts|outlook|estimates\s+for)\b",
        language="en",
        weight=1.0,
        note="Names the projection itself, so the statement is about an expectation.",
    ),
    Cue(
        id="en.forecast.horizon_phrase",
        pattern=r"\b(?:by\s+(?:19|20)\d{2}|over\s+the\s+next|in\s+the\s+coming|within\s+\w+\s+years?)\b",
        language="en",
        weight=0.8,
        note="Forward-looking time frame.",
    ),
    Cue(
        id="es.forecast.synthetic_future",
        pattern=r"\b\w{3,}(?:ar[aá]|er[aá]|ir[aá]|ar[aá]n|er[aá]n|ir[aá]n|ar[eé]|ar[aá]s)\b",
        language="es",
        weight=1.2,
        note="Spanish synthetic future morphology (-ará/-erán/…): the verb itself is future-tense.",
        exclude=_ES_FUTURE_FALSE_POSITIVES,
    ),
    Cue(
        id="es.forecast.ir_a",
        pattern=r"\b(?:va|van|vamos|voy)\s+a\s+\w+r\b",
        language="es",
        weight=1.2,
        note="Periphrastic future 'ir a + infinitivo'.",
    ),
    Cue(
        id="es.forecast.se_espera",
        pattern=r"\b(?:se\s+espera|se\s+proyecta|se\s+prev[ée]|se\s+estima|se\s+anticipa)\b",
        language="es",
        weight=1.5,
        note="Impersonal projection framing: reports an expectation rather than an observation.",
    ),
    Cue(
        id="es.forecast.projection_noun",
        pattern=r"\b(?:proyecci[oó]n|proyecciones|previsi[oó]n|previsiones|pron[oó]stico|estimaci[oó]n\s+para)\b",
        language="es",
        weight=1.0,
        note="Names the projection itself.",
    ),
    Cue(
        id="es.forecast.horizon_phrase",
        pattern=(
            r"\b(?:de\s+aqu[ií]\s+a|en\s+los\s+pr[oó]ximos|hacia\s+(?:19|20)\d{2}"
            r"|para\s+(?:19|20)\d{2}|dentro\s+de\s+\w+\s+a[nñ]os?)\b"
        ),
        language="es",
        weight=0.8,
        note="Forward-looking time frame.",
    ),
)

OPINION_CUES: Final[tuple[Cue, ...]] = (
    Cue(
        id="en.opinion.first_person_stance",
        pattern=r"\b(?:i\s+(?:believe|think|feel)|in\s+my\s+(?:view|opinion)|to\s+my\s+mind|frankly)\b",
        language="en",
        weight=1.8,
        note="Explicitly marks the statement as the speaker's own stance.",
    ),
    Cue(
        id="en.opinion.evaluative_adjective",
        pattern=(
            r"\b(?:terrible|disastrous|catastrophic|excellent|brilliant|absurd|ridiculous"
            r"|outrageous|shameful|disgraceful|unfair|unjust|wonderful|awful|reckless"
            r"|irresponsible|cynical|scandalous|unacceptable|magnificent|dreadful)\b"
        ),
        language="en",
        weight=1.5,
        note="Evaluative adjective: expresses approval or disapproval rather than a checkable property.",
    ),
    Cue(
        id="en.opinion.superlative_stance",
        pattern=r"\b(?:the\s+(?:best|worst)\s+\w+\s+(?:ever|in\s+\w+\s+years))\b",
        language="en",
        weight=1.2,
        note="Superlative used as praise or condemnation rather than as a measured ranking.",
    ),
    Cue(
        id="es.opinion.first_person_stance",
        pattern=(
            r"\b(?:creo\s+que|pienso\s+que|me\s+parece|a\s+mi\s+juicio|en\s+mi\s+opini[oó]n"
            r"|considero\s+que|francamente)\b"
        ),
        language="es",
        weight=1.8,
        note="Explicitly marks the statement as the speaker's own stance.",
    ),
    Cue(
        id="es.opinion.evaluative_adjective",
        pattern=(
            r"\b(?:terrible|desastros[oa]s?|catastr[oó]fic[oa]s?|excelente|absurd[oa]s?"
            r"|rid[ií]cul[oa]s?|indignante|vergonzos[oa]s?|injust[oa]s?|maravillos[oa]s?"
            r"|nefast[oa]s?|irresponsable|c[ií]nic[oa]s?|escandalos[oa]s?|inaceptable"
            r"|lamentable|temerari[oa]s?|brillante)\b"
        ),
        language="es",
        weight=1.5,
        note="Evaluative adjective: expresses approval or disapproval rather than a checkable property.",
    ),
)

NORMATIVE_CUES: Final[tuple[Cue, ...]] = (
    Cue(
        id="en.normative.deontic_modal",
        pattern=r"\b(?:should|ought\s+to|must)\s+(?:not\s+|never\s+)?(?:be\s+)?[a-z]+",
        language="en",
        weight=1.5,
        note="Deontic modal: asserts what ought to be done rather than what is the case.",
    ),
    Cue(
        id="en.normative.necessity_frame",
        pattern=(
            r"\b(?:needs?\s+to\s+be|has\s+to\s+be|have\s+to\s+be|it\s+is\s+necessary\s+to"
            r"|it\s+is\s+imperative|there\s+is\s+a\s+duty\s+to|we\s+(?:must|need\s+to))\b"
        ),
        language="en",
        weight=1.5,
        note="States a requirement or duty, not an observation.",
    ),
    Cue(
        id="es.normative.deontic_modal",
        # The infinitive may carry an enclitic pronoun ("reducirse", "aplicarlo"),
        # which the bare \w+r\b form missed — and missing it published "el gasto
        # debería reducirse" as a checkable fact.
        pattern=(
            r"\b(?:deber[ií]an?|deben?|debemos|deber[ií]amos)\s+(?:de\s+)?"
            r"\w+r(?:se|le|lo|la|los|las|nos|me|te)?\b"
        ),
        language="es",
        weight=1.5,
        note="Deontic 'deber + infinitivo': asserts an obligation.",
    ),
    Cue(
        id="es.normative.necessity_frame",
        pattern=(
            r"\b(?:hay\s+que|es\s+necesario|es\s+imprescindible|es\s+urgente|urge\s+\w+r"
            r"|corresponde\s+\w+r|tiene\s+que|tienen\s+que|no\s+se\s+puede\s+permitir"
            r"|es\s+un\s+deber)\b"
        ),
        language="es",
        weight=1.5,
        note="States a requirement or duty, not an observation.",
    ),
)

INTERPRETATION_CUES: Final[tuple[Cue, ...]] = (
    Cue(
        id="en.interpretation.inference_verb",
        pattern=(
            r"\b(?:suggests?|indicates?|implies|means\s+that|amounts?\s+to|reflects?"
            r"|points?\s+to|can\s+be\s+read\s+as|represents?\s+an?)\b"
        ),
        language="en",
        weight=1.4,
        note="Presents a reading of evidence rather than the evidence itself.",
    ),
    Cue(
        id="en.interpretation.in_effect",
        pattern=r"\b(?:in\s+effect|effectively|in\s+practice|essentially|in\s+substance)\b",
        language="en",
        weight=1.2,
        note="Signals a characterisation of what something amounts to.",
    ),
    Cue(
        id="es.interpretation.inference_verb",
        pattern=(
            r"\b(?:sugiere|indica|implica|significa\s+que|equivale\s+a|refleja"
            r"|apunta\s+a|supone\s+un|representa\s+un|se\s+traduce\s+en)\b"
        ),
        language="es",
        weight=1.4,
        note="Presents a reading of evidence rather than the evidence itself.",
    ),
    Cue(
        id="es.interpretation.en_la_practica",
        pattern=r"\b(?:en\s+la\s+pr[aá]ctica|en\s+el\s+fondo|en\s+rigor|en\s+t[eé]rminos\s+pr[aá]cticos)\b",
        language="es",
        weight=1.2,
        note="Signals a characterisation of what something amounts to.",
    ),
)

FACT_CUES: Final[tuple[Cue, ...]] = (
    Cue(
        id="en.fact.attributed_record",
        pattern=(
            r"\b(?:according\s+to\s+the\s+(?:report|document|data|figures|text)"
            r"|the\s+(?:report|document|text)\s+states|the\s+data\s+shows?"
            r"|figures\s+show|records?\s+show)\b"
        ),
        language="en",
        weight=1.6,
        note="Anchors the statement in a document or dataset, which is checkable.",
    ),
    Cue(
        id="en.fact.past_measurement",
        pattern=(
            r"\b(?:increased|decreased|rose|fell|amounted\s+to|totalled|totaled|reached"
            r"|stood\s+at|was\s+recorded|were\s+recorded)\b"
        ),
        language="en",
        weight=1.1,
        note="Past-tense measurement verb: reports something already observed.",
    ),
    Cue(
        id="es.fact.attributed_record",
        pattern=(
            r"\b(?:seg[uú]n\s+el\s+(?:informe|documento|texto|proyecto)"
            r"|el\s+(?:informe|documento|texto)\s+(?:establece|se[nñ]ala|indica)"
            r"|los\s+datos\s+muestran|las\s+cifras\s+muestran)\b"
        ),
        language="es",
        weight=1.6,
        note="Anchors the statement in a document or dataset, which is checkable.",
    ),
    Cue(
        id="es.fact.past_measurement",
        pattern=(
            r"\b(?:aument[oó]|disminuy[oó]|subi[oó]|baj[oó]|ascendi[oó]\s+a|alcanz[oó]"
            r"|se\s+situ[oó]\s+en|registr[oó]|totaliz[oó]|fue\s+de|lleg[oó]\s+a)\b"
        ),
        language="es",
        weight=1.1,
        note="Preterite measurement verb: reports something already observed.",
    ),
)

CONDITIONAL_CUES: Final[tuple[Cue, ...]] = (
    Cue(
        id="en.conditional.if",
        pattern=r"\b(?:if|unless|provided\s+that|in\s+the\s+event\s+that|as\s+long\s+as)\b",
        language="en",
        weight=1.0,
        note="Antecedent: the statement holds only when its condition holds.",
    ),
    Cue(
        id="en.conditional.would",
        pattern=r"\b(?:would|could)\s+(?:not\s+)?[a-z]+",
        language="en",
        weight=0.8,
        note="Conditional mood: describes a contingent rather than an actual state.",
    ),
    Cue(
        id="es.conditional.si",
        pattern=r"\b(?:si|a\s+menos\s+que|salvo\s+que|siempre\s+que|en\s+caso\s+de\s+que|de\s+no\s+\w+r)\b",
        language="es",
        weight=1.0,
        note="Antecedent: the statement holds only when its condition holds.",
    ),
    Cue(
        id="es.conditional.mood",
        pattern=r"\b\w{3,}(?:ar[ií]a|er[ií]a|ir[ií]a|ar[ií]an|er[ií]an|ir[ií]an)\b",
        language="es",
        weight=0.8,
        note="Spanish conditional morphology (-aría/-erían/…): contingent rather than actual.",
    ),
)

HEDGE_CUES: Final[tuple[Cue, ...]] = (
    Cue(
        id="en.hedge.epistemic_modal",
        pattern=r"\b(?:may|might|could|possibly|potentially|perhaps|arguably|likely|roughly|approximately|around|about)\b",
        language="en",
        weight=1.0,
        note="Hedge: the speaker signals the statement is not asserted with full confidence.",
    ),
    Cue(
        id="es.hedge.epistemic",
        pattern=(
            r"\b(?:quiz[aá]s?|tal\s+vez|posiblemente|probablemente|eventualmente"
            r"|aproximadamente|cerca\s+de|en\s+torno\s+a|alrededor\s+de|podr[ií]an?)\b"
        ),
        language="es",
        weight=1.0,
        note="Hedge: the speaker signals the statement is not asserted with full confidence.",
    ),
)

CERTAINTY_CUES: Final[tuple[Cue, ...]] = (
    Cue(
        id="en.certainty.absolute",
        pattern=(
            r"\b(?:definitely|certainly|undoubtedly|without\s+(?:a\s+)?doubt|guaranteed"
            r"|obviously|clearly|inevitably|beyond\s+question)\b"
        ),
        language="en",
        weight=1.0,
        note="Certainty marker. Recorded because certainty asserted over a projection is a "
        "reportable inflation of confidence, never a reason to believe the projection.",
    ),
    Cue(
        id="es.certainty.absolute",
        pattern=(
            r"\b(?:sin\s+duda|con\s+certeza|indudablemente|obviamente|evidentemente"
            r"|garantizad[oa]s?|inevitablemente|sin\s+lugar\s+a\s+dudas)\b"
        ),
        language="es",
        weight=1.0,
        note="Certainty marker. Recorded because certainty asserted over a projection is a "
        "reportable inflation of confidence, never a reason to believe the projection.",
    ),
)

CAUSAL_CUES: Final[tuple[Cue, ...]] = (
    Cue(
        id="en.causal.explicit",
        pattern=(
            r"\b(?:causes?|caused|leads?\s+to|led\s+to|results?\s+in|resulted\s+in"
            r"|drives?|because\s+of|due\s+to|as\s+a\s+result\s+of|triggers?)\b"
        ),
        language="en",
        weight=1.0,
        note="Asserts a causal link, which needs evidence beyond correlation or sequence.",
    ),
    Cue(
        id="es.causal.explicit",
        pattern=(
            r"\b(?:causa|caus[oó]|provoca|provoc[oó]|genera|gener[oó]|produce|produjo"
            r"|se\s+debe\s+a|debido\s+a|a\s+causa\s+de|como\s+resultado\s+de|deriva\s+en)\b"
        ),
        language="es",
        weight=1.0,
        note="Asserts a causal link, which needs evidence beyond correlation or sequence.",
    ),
)

UNIVERSAL_CUES: Final[tuple[Cue, ...]] = (
    Cue(
        id="en.universal.quantifier",
        pattern=r"\b(?:all|every|always|never|no\s+one|nobody|none\s+of|without\s+exception)\b",
        language="en",
        weight=1.0,
        note="Universal quantifier: raises the evidential bar, since one counterexample refutes it.",
    ),
    Cue(
        id="es.universal.quantifier",
        pattern=(
            r"\b(?:tod[oa]s\s+l[oa]s|cada|siempre|nunca|jam[aá]s|ning[uú]n[oa]?"
            r"|nadie|sin\s+excepci[oó]n)\b"
        ),
        language="es",
        weight=1.0,
        note="Universal quantifier: raises the evidential bar, since one counterexample refutes it.",
    ),
)

ASSUMPTION_CUES: Final[tuple[Cue, ...]] = (
    Cue(
        id="en.assumption.explicit",
        pattern=(
            r"\b(?:assuming|on\s+the\s+assumption\s+that|provided\s+that|subject\s+to"
            r"|based\s+on\s+(?:the\s+)?(?:assumption|projection|estimate)s?"
            r"|conditional\s+on|so\s+long\s+as)\b"
        ),
        language="en",
        weight=1.0,
        note="Names a condition the statement depends on.",
    ),
    Cue(
        id="es.assumption.explicit",
        pattern=(
            r"\b(?:suponiendo|asumiendo|bajo\s+el\s+supuesto\s+de|sobre\s+la\s+base\s+de"
            r"|en\s+base\s+a|condicionad[oa]\s+a|siempre\s+que|si\s+se\s+cumple)\b"
        ),
        language="es",
        weight=1.0,
        note="Names a condition the statement depends on.",
    ),
)

QUANTITY_CUES: Final[tuple[Cue, ...]] = (
    Cue(
        id="xx.quantity.numeral",
        pattern=r"(?<![\w.,])\d[\d.,]*(?:\s*(?:%|per\s*cent|percent|por\s+ciento))?",
        language="xx",
        weight=0.6,
        note="Contains a numeral, so the claim carries something arithmetically checkable.",
    ),
)

#: Every cue family, keyed by name. Public so a test or a UI can enumerate the
#: vocabulary without importing each tuple by hand.
CUE_FAMILIES: Final[Mapping[str, tuple[Cue, ...]]] = {
    "forecast": FORECAST_CUES,
    "opinion": OPINION_CUES,
    "normative": NORMATIVE_CUES,
    "interpretation": INTERPRETATION_CUES,
    "fact": FACT_CUES,
    "conditional": CONDITIONAL_CUES,
    "hedge": HEDGE_CUES,
    "certainty": CERTAINTY_CUES,
    "causal": CAUSAL_CUES,
    "universal": UNIVERSAL_CUES,
    "assumption": ASSUMPTION_CUES,
    "quantity": QUANTITY_CUES,
}

#: Families that name a statement type directly.
TYPED_FAMILIES: Final[Mapping[str, StatementType]] = {
    "forecast": StatementType.FORECAST,
    "opinion": StatementType.OPINION,
    "normative": StatementType.NORMATIVE,
    "interpretation": StatementType.INTERPRETATION,
    "fact": StatementType.FACT,
}

#: How a modifier family shifts the score of each statement type.
#:
#: A conditional leans towards forecast and interpretation and away from fact,
#: because a statement whose truth is contingent is not a plain report. A hedge
#: does the same, more weakly. A causal assertion leans towards interpretation,
#: because "A caused B" is a reading of a relationship rather than a direct
#: observation of one. Certainty markers, universal quantifiers and numerals
#: shift nothing: they matter to the *checks*, not to the category.
FAMILY_CONTRIBUTIONS: Final[Mapping[str, Mapping[StatementType, float]]] = {
    "conditional": {
        StatementType.FORECAST: 0.5,
        StatementType.INTERPRETATION: 0.2,
        StatementType.FACT: -0.4,
    },
    "hedge": {
        StatementType.FORECAST: 0.2,
        StatementType.INTERPRETATION: 0.2,
        StatementType.FACT: -0.3,
    },
    "causal": {StatementType.INTERPRETATION: 0.4},
    "certainty": {},
    "universal": {},
    "assumption": {StatementType.FORECAST: 0.3},
    "quantity": {StatementType.FACT: 0.3},
}

#: The starting score of each type before any cue fires.
#:
#: ``fact`` starts ahead because an unmarked declarative sentence normally does
#: assert something about the world, and a system that classified every bare
#: sentence as 'interpretation' would refuse to check anything.
BASELINE_SCORES: Final[Mapping[StatementType, float]] = {
    StatementType.FACT: 1.0,
    StatementType.INTERPRETATION: 0.0,
    StatementType.FORECAST: 0.0,
    StatementType.OPINION: 0.0,
    StatementType.NORMATIVE: 0.0,
}

#: Precedence when two types score equally. Deliberately ordered away from
#: ``fact``: presenting a forecast or an opinion as a checkable fact is the more
#: damaging error, so a tie resolves to the more cautious category.
TIE_BREAK_ORDER: Final[tuple[StatementType, ...]] = (
    StatementType.NORMATIVE,
    StatementType.OPINION,
    StatementType.FORECAST,
    StatementType.INTERPRETATION,
    StatementType.FACT,
)

# Compiled once at import. No cue is compiled lazily, so a malformed pattern
# fails at import rather than on the one claim that happens to trigger it.
_COMPILED: Final[dict[str, re.Pattern[str]]] = {
    cue.id: re.compile(cue.pattern, re.IGNORECASE | re.UNICODE)
    for family in CUE_FAMILIES.values()
    for cue in family
}
_CUE_BY_ID: Final[dict[str, tuple[str, Cue]]] = {
    cue.id: (family_name, cue) for family_name, family in CUE_FAMILIES.items() for cue in family
}


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_ES_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "que",
        "en",
        "por",
        "para",
        "con",
        "una",
        "un",
        "se",
        "es",
        "son",
        "no",
        "al",
        "como",
        "más",
        "pero",
        "su",
    }
)
_EN_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "of",
        "and",
        "to",
        "in",
        "that",
        "is",
        "are",
        "for",
        "with",
        "on",
        "as",
        "by",
        "from",
        "will",
        "not",
        "it",
        "this",
        "an",
        "be",
    }
)
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[^\W\d_]+", re.UNICODE)


def _fold(text: str) -> str:
    """Lowercase and strip combining marks, for accent-insensitive comparison."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def detect_language(text: str) -> str:
    """Return ``'es'``, ``'en'`` or ``'xx'`` for a claim string.

    A deliberately crude function-word count. It exists to decide which cue set
    to trust more, not to be a language identifier: a wrong answer costs a little
    precision in the cue weighting and nothing else, because cues from both
    languages are always evaluated.

    Ties and empty inputs return ``'xx'``, which weights both cue sets equally.
    """
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if not words:
        return "xx"
    es = sum(1 for w in words if w in _ES_MARKERS)
    en = sum(1 for w in words if w in _EN_MARKERS)
    if es > en:
        return "es"
    if en > es:
        return "en"
    return "xx"


# ---------------------------------------------------------------------------
# Cue matching
# ---------------------------------------------------------------------------


def find_cues(text: str, *, language: str | None = None) -> tuple[CueHit, ...]:
    """Return every cue found in ``text``, in order of appearance.

    All cues from every language are tried regardless of the detected language.
    Cues from a non-matching language are kept but down-weighted rather than
    discarded, because mixed-language quotation is ordinary in policy coverage
    and dropping the "wrong" language's cues would silently mis-type a
    code-switched sentence.

    Args:
        text: The claim, as it will be classified.
        language: Detected language tag; computed with :func:`detect_language`
            when omitted.

    Returns:
        Hits sorted by ``char_start`` then ``cue_id``, so the sequence is stable
        for a given input.
    """
    lang = language or detect_language(text)
    hits: list[CueHit] = []
    for cue_id, pattern in _COMPILED.items():
        family_name, cue = _CUE_BY_ID[cue_id]
        for match in pattern.finditer(text):
            surface = match.group(0)
            if cue.exclude and _fold(surface.strip()) in cue.exclude:
                continue
            weight = cue.weight
            if cue.language not in {"xx", lang} and lang != "xx":
                # A cue from the other language still counts — code-switching is
                # common — but is trusted less than a cue in the matrix language.
                weight *= 0.6
            hits.append(
                CueHit(
                    cue_id=cue.id,
                    family=family_name,
                    matched_text=surface,
                    char_start=match.start(),
                    char_end=match.end(),
                    language=cue.language,
                    weight=round(weight, 4),
                    note=cue.note,
                )
            )
    hits.sort(key=lambda hit: (hit.char_start, hit.cue_id))
    return tuple(hits)


def is_quantitative(text: str) -> bool:
    """Return whether the text contains a numeral available for arithmetic checking."""
    return _COMPILED["xx.quantity.numeral"].search(text) is not None


# ---------------------------------------------------------------------------
# Assumptions behind a forecast
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ForecastAssumption:
    """One condition a forward-looking claim depends on.

    ``is_explicit`` is the load-bearing field. A condition the speaker stated is
    evidence about what they claimed; a condition inherent in making a projection
    at all is Aleph's own observation about the form of the statement. Presenting
    the second as the first would attribute to a speaker an admission they never
    made, so the two are never merged.
    """

    statement: str
    assumption_type: AssumptionType
    is_explicit: bool
    cue_text: str | None = None
    char_start: int | None = None
    char_end: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {
            "statement": self.statement,
            "assumption_type": self.assumption_type.value,
            "is_explicit": self.is_explicit,
            "cue_text": self.cue_text,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }


# Structural assumptions that any projection carries whether or not it says so.
# Each is gated on a signal in the claim, so a projection about a benefit does
# not acquire a macroeconomic assumption it never depended on.
_MACRO_SIGNALS: Final[re.Pattern[str]] = re.compile(
    r"\b(?:gdp|pib|growth|crecimiento|inflation|inflaci[oó]n|revenue|recaudaci[oó]n"
    r"|deficit|d[eé]ficit|interest\s+rate|tasa\s+de\s+inter[eé]s|exchange\s+rate|tipo\s+de\s+cambio)\b",
    re.IGNORECASE,
)
_TAKE_UP_SIGNALS: Final[re.Pattern[str]] = re.compile(
    r"\b(?:beneficiar\w*|beneficiaries|recipients|households|hogares|families|familias"
    r"|applicants|solicitantes|cobertura|coverage|take[-\s]?up)\b",
    re.IGNORECASE,
)
_BEHAVIOURAL_SIGNALS: Final[re.Pattern[str]] = re.compile(
    r"\b(?:demand|demanda|behaviour|behavior|comportamiento|response|respuesta"
    r"|incentive|incentivo|compliance|cumplimiento|evasion|evasi[oó]n|hiring|contrataci[oó]n)\b",
    re.IGNORECASE,
)


def detect_assumptions(
    text: str,
    *,
    cues: Sequence[CueHit] | None = None,
    statement_type: StatementType | None = None,
) -> tuple[ForecastAssumption, ...]:
    """Recover the conditions a forward-looking claim rests on.

    Explicit assumptions come first: the clause following an assumption or
    conditional marker is captured verbatim, because paraphrasing a stated
    condition is how a caveat quietly disappears.

    Structural assumptions are added only for forecasts, only when the claim
    carries the corresponding signal, and always with ``is_explicit=False``. They
    exist because a projection with no stated conditions is not thereby
    unconditional — it is a projection whose conditions were left implicit, and
    naming them is what lets a later reader ask whether they held.

    Args:
        text: The claim text.
        cues: Cue hits already computed for this text, to avoid re-matching.
        statement_type: The classified type; structural assumptions are added
            only when this is :attr:`~aleph.core.enums.StatementType.FORECAST`.

    Returns:
        Explicit assumptions in order of appearance, then structural ones.
    """
    hits = tuple(cues) if cues is not None else find_cues(text)
    explicit: list[ForecastAssumption] = []
    seen: set[str] = set()

    for hit in hits:
        if hit.family not in {"assumption", "conditional"}:
            continue
        tail = text[hit.char_start :]
        clause = _first_clause(tail)
        if not clause or len(clause.split()) < 2:
            continue
        key = _fold(clause)
        if key in seen:
            continue
        seen.add(key)
        explicit.append(
            ForecastAssumption(
                statement=clause,
                assumption_type=_assumption_type_for(clause),
                is_explicit=True,
                cue_text=hit.matched_text,
                char_start=hit.char_start,
                char_end=hit.char_start + len(clause),
            )
        )

    if statement_type is not StatementType.FORECAST:
        return tuple(explicit)

    structural: list[ForecastAssumption] = [
        ForecastAssumption(
            statement=(
                "The measure is implemented as written, on the timetable the text sets out."
            ),
            assumption_type=AssumptionType.IMPLEMENTATION,
            is_explicit=False,
        ),
        ForecastAssumption(
            statement=(
                "No offsetting change of policy or external shock occurs within the "
                "projection period."
            ),
            assumption_type=AssumptionType.EXTERNAL_CONDITION,
            is_explicit=False,
        ),
    ]
    if _MACRO_SIGNALS.search(text):
        structural.append(
            ForecastAssumption(
                statement=(
                    "The macroeconomic path underlying the projected figure holds over the "
                    "projection period."
                ),
                assumption_type=AssumptionType.MACROECONOMIC,
                is_explicit=False,
            )
        )
    if _TAKE_UP_SIGNALS.search(text):
        structural.append(
            ForecastAssumption(
                statement="Uptake among the eligible population matches the projected level.",
                assumption_type=AssumptionType.TAKE_UP,
                is_explicit=False,
            )
        )
    if _BEHAVIOURAL_SIGNALS.search(text):
        structural.append(
            ForecastAssumption(
                statement=(
                    "Those affected respond to the measure in the way the projection assumes."
                ),
                assumption_type=AssumptionType.BEHAVIOURAL,
                is_explicit=False,
            )
        )
    return tuple(explicit) + tuple(structural)


_CLAUSE_END: Final[re.Pattern[str]] = re.compile(r"[,;.:!?]|\s+(?:then|entonces)\s+", re.IGNORECASE)


def _first_clause(text: str, *, max_words: int = 25) -> str:
    """Return the clause beginning at ``text``, up to the first boundary."""
    match = _CLAUSE_END.search(text)
    clause = text[: match.start()] if match else text
    words = clause.split()
    return " ".join(words[:max_words]).strip()


def _assumption_type_for(clause: str) -> AssumptionType:
    """Classify a stated assumption by what kind of thing it takes for granted."""
    if _MACRO_SIGNALS.search(clause):
        return AssumptionType.MACROECONOMIC
    if _TAKE_UP_SIGNALS.search(clause):
        return AssumptionType.TAKE_UP
    if _BEHAVIOURAL_SIGNALS.search(clause):
        return AssumptionType.BEHAVIOURAL
    if re.search(
        r"\b(?:approved|enacted|passed|aprobad|promulgad|entre\s+en\s+vigor|comes\s+into\s+force)\b",
        clause,
        re.IGNORECASE,
    ):
        return AssumptionType.IMPLEMENTATION
    if re.search(
        r"\b(?:comply|compliance|cumplan?|cumplimiento|evasion|evasi[oó]n)\b",
        clause,
        re.IGNORECASE,
    ):
        return AssumptionType.COMPLIANCE
    return AssumptionType.EXTERNAL_CONDITION


# ---------------------------------------------------------------------------
# Time horizon
# ---------------------------------------------------------------------------

_HORIZON_PATTERNS: Final[tuple[tuple[TimeHorizon, re.Pattern[str]], ...]] = (
    (
        TimeHorizon.IMMEDIATE,
        re.compile(
            r"\b(?:immediately|right\s+away|at\s+once|de\s+inmediato|inmediatamente"
            r"|de\s+forma\s+inmediata|desde\s+ya)\b",
            re.IGNORECASE,
        ),
    ),
    (
        TimeHorizon.SHORT_TERM,
        re.compile(
            r"\b(?:this\s+year|next\s+year|within\s+(?:the\s+)?(?:next\s+)?(?:12|twelve)\s+months"
            r"|corto\s+plazo|este\s+a[nñ]o|el\s+pr[oó]ximo\s+a[nñ]o|en\s+doce\s+meses)\b",
            re.IGNORECASE,
        ),
    ),
    (
        TimeHorizon.MEDIUM_TERM,
        re.compile(
            r"\b(?:medium[-\s]term|mediano\s+plazo|over\s+the\s+next\s+(?:two|three|four|five)"
            r"|en\s+los\s+pr[oó]ximos\s+(?:dos|tres|cuatro|cinco)|dentro\s+de\s+(?:tres|cuatro|cinco)\s+a[nñ]os)\b",
            re.IGNORECASE,
        ),
    ),
    (
        TimeHorizon.LONG_TERM,
        re.compile(
            r"\b(?:long[-\s]term|largo\s+plazo|over\s+a\s+decade|in\s+a\s+decade"
            r"|en\s+una\s+d[eé]cada|a\s+diez\s+a[nñ]os|generational|generacional)\b",
            re.IGNORECASE,
        ),
    ),
)


def detect_time_horizon(text: str) -> TimeHorizon:
    """Return the time frame a forward-looking claim names, if it names one.

    Lexical only: no clock is read and no year arithmetic is done, because doing
    either would make the same claim classify differently depending on when the
    pipeline happened to run, and a horizon that drifts is worse than one that is
    honestly ``unknown``.
    """
    for horizon, pattern in _HORIZON_PATTERNS:
        if pattern.search(text):
            return horizon
    return TimeHorizon.UNKNOWN


# ---------------------------------------------------------------------------
# The classification itself
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClaimClassification:
    """What kind of statement this is, and everything that led to that answer.

    The scores and the cue list are returned rather than logged because this
    classification decides how a claim is *presented*: a ``forecast`` is shown
    with its assumptions and can never be marked ``supported``, an ``opinion`` is
    never given a truth verdict at all. A reader who disagrees with that framing
    is entitled to see the sentence-level reason for it.
    """

    statement_type: StatementType
    scores: Mapping[StatementType, float]
    cues: tuple[CueHit, ...]
    language: str
    assumptions: tuple[ForecastAssumption, ...] = ()
    time_horizon: TimeHorizon = TimeHorizon.UNKNOWN
    is_falsifiable: bool = True
    is_quantitative: bool = False
    is_compound: bool = False
    asserts_causation: bool = False
    asserts_universal: bool = False
    asserts_certainty: bool = False
    is_hedged: bool = False
    is_conditional: bool = False
    margin: float = 0.0
    """Gap between the winning score and the runner-up. A small margin means the
    sentence carried mixed signals, and downstream confidence is lowered for it."""
    rationale: str = ""
    classifier_version: str = CLASSIFIER_VERSION

    @property
    def is_checkable_fact(self) -> bool:
        """Whether this statement may be given a true/false verdict at all."""
        return self.statement_type in {StatementType.FACT, StatementType.INTERPRETATION}

    def cues_for(self, family: str) -> tuple[CueHit, ...]:
        """Return the hits belonging to one cue family."""
        return tuple(hit for hit in self.cues if hit.family == family)

    def explicit_assumptions(self) -> tuple[ForecastAssumption, ...]:
        """Return only the assumptions the claim itself stated."""
        return tuple(a for a in self.assumptions if a.is_explicit)

    def assumption_statements(self) -> list[str]:
        """Return assumption text for ``BlindEvaluation.assumptions_required``.

        Structural assumptions are prefixed so a reader can tell what the speaker
        conditioned their claim on from what the form of a projection implies.
        """
        out: list[str] = []
        for assumption in self.assumptions:
            prefix = "" if assumption.is_explicit else "Implied by the projection: "
            out.append(f"{prefix}{assumption.statement}")
        return out

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping for diagnostics and UI display."""
        return {
            "statement_type": self.statement_type.value,
            "scores": {k.value: round(v, 4) for k, v in self.scores.items()},
            "cues": [hit.as_dict() for hit in self.cues],
            "language": self.language,
            "assumptions": [a.as_dict() for a in self.assumptions],
            "time_horizon": self.time_horizon.value,
            "is_falsifiable": self.is_falsifiable,
            "is_quantitative": self.is_quantitative,
            "is_compound": self.is_compound,
            "asserts_causation": self.asserts_causation,
            "asserts_universal": self.asserts_universal,
            "asserts_certainty": self.asserts_certainty,
            "is_hedged": self.is_hedged,
            "is_conditional": self.is_conditional,
            "margin": round(self.margin, 4),
            "rationale": self.rationale,
            "classifier_version": self.classifier_version,
        }


_COMPOUND_RE: Final[re.Pattern[str]] = re.compile(
    r",\s+(?:and|but|while|whereas|y|pero|mientras|aunque)\s+\w+|\band\s+also\b|\by\s+adem[aá]s\b",
    re.IGNORECASE,
)


def classify_claim_text(
    text: str,
    *,
    language: str | None = None,
    cues: Sequence[CueHit] | None = None,
) -> ClaimClassification:
    """Classify one claim as fact, interpretation, forecast, opinion or normative.

    The procedure is: start from :data:`BASELINE_SCORES`, add each cue's weight to
    the score of its family's type, apply the modifier contributions in
    :data:`FAMILY_CONTRIBUTIONS`, take the maximum, and break ties with
    :data:`TIE_BREAK_ORDER`. Every step is data-driven and every step is
    reported back, which is the point: this is a classification a reader can
    audit line by line, not a label from an oracle.

    Args:
        text: The claim to classify. Should be the normalised single proposition
            rather than a whole paragraph — a paragraph will mix cue families and
            produce a small, honest ``margin``.
        language: Override for the detected language.
        cues: Pre-computed cue hits, to avoid re-matching.

    Returns:
        A :class:`ClaimClassification`. Never raises on ordinary text; an empty
        string classifies as ``fact`` with an empty cue list and a zero margin,
        which downstream treats as maximally ambiguous.
    """
    lang = language or detect_language(text)
    hits = tuple(cues) if cues is not None else find_cues(text, language=lang)

    scores: dict[StatementType, float] = dict(BASELINE_SCORES)
    # Typed cues accumulate: three separate markers of futurity really are
    # stronger evidence of a forecast than one. Modifier families do NOT — a
    # sentence with three numerals is not three times more factual, and letting
    # them stack meant a projection carrying several figures outscored its own
    # future-tense verb and was published as a checkable fact.
    modifier_peak: dict[str, float] = {}
    for hit in hits:
        typed = TYPED_FAMILIES.get(hit.family)
        if typed is not None:
            scores[typed] = scores.get(typed, 0.0) + hit.weight
            continue
        modifier_peak[hit.family] = max(modifier_peak.get(hit.family, 0.0), hit.weight)
    for family, peak in modifier_peak.items():
        for statement_type, delta in FAMILY_CONTRIBUTIONS.get(family, {}).items():
            scores[statement_type] = scores.get(statement_type, 0.0) + delta * peak

    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1], TIE_BREAK_ORDER.index(item[0])),
    )
    winner, top_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = max(0.0, top_score - runner_up)

    families_present = {hit.family for hit in hits}
    is_conditional = "conditional" in families_present
    is_hedged = "hedge" in families_present
    asserts_certainty = "certainty" in families_present
    asserts_causation = "causal" in families_present
    asserts_universal = "universal" in families_present
    quantitative = "quantity" in families_present

    assumptions = detect_assumptions(text, cues=hits, statement_type=winner)
    horizon = detect_time_horizon(text) if winner is StatementType.FORECAST else TimeHorizon.UNKNOWN

    # A forecast is falsifiable only if there is something to check and a point
    # at which to check it. "Things will improve" is rhetoric; saying so is not a
    # criticism of the speaker, but presenting it as a checkable prediction would
    # be a misrepresentation of what was said.
    falsifiable = True
    if winner is StatementType.FORECAST:
        falsifiable = quantitative or horizon is not TimeHorizon.UNKNOWN
    elif winner in {StatementType.OPINION, StatementType.NORMATIVE}:
        falsifiable = False

    rationale = _build_rationale(winner, hits, margin, lang)

    return ClaimClassification(
        statement_type=winner,
        scores=dict(scores),
        cues=hits,
        language=lang,
        assumptions=assumptions,
        time_horizon=horizon,
        is_falsifiable=falsifiable,
        is_quantitative=quantitative,
        is_compound=bool(_COMPOUND_RE.search(text)),
        asserts_causation=asserts_causation,
        asserts_universal=asserts_universal,
        asserts_certainty=asserts_certainty,
        is_hedged=is_hedged,
        is_conditional=is_conditional,
        margin=margin,
        rationale=rationale,
    )


#: Alias matching the vocabulary used elsewhere in the pipeline.
classify_statement = classify_claim_text


def _build_rationale(
    statement_type: StatementType,
    hits: Sequence[CueHit],
    margin: float,
    language: str,
) -> str:
    """Write the one-paragraph explanation that ships with the classification."""
    typed_hits = [h for h in hits if TYPED_FAMILIES.get(h.family) is statement_type]
    if not typed_hits:
        base = (
            f"No cue for '{statement_type.value}' fired; the statement is a bare declarative "
            "and falls to the documented default, which treats an unmarked assertion as a "
            "claim about the world."
        )
    else:
        quoted = ", ".join(f"{h.matched_text.strip()!r} ({h.cue_id})" for h in typed_hits[:4])
        base = f"Classified '{statement_type.value}' on {len(typed_hits)} cue(s): {quoted}."
    modifiers = sorted({h.family for h in hits} - set(TYPED_FAMILIES))
    if modifiers:
        base += f" Modifying signals present: {', '.join(modifiers)}."
    if margin < 0.5:
        base += (
            f" The margin over the runner-up type is only {margin:.2f}, so the sentence "
            "carries mixed signals and downstream confidence is reduced accordingly."
        )
    base += f" Detected language: {language}."
    return base


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClassificationBatch:
    """Classifications for several claims, with their aggregate shape.

    ``type_counts`` is worth surfacing on its own: a set of claims that is 80%
    forecast tells a reader something important about a debate before any
    individual verdict is read.
    """

    classifications: tuple[ClaimClassification, ...]
    type_counts: Mapping[StatementType, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {
            "classifications": [c.as_dict() for c in self.classifications],
            "type_counts": {k.value: v for k, v in self.type_counts.items()},
        }


def classify_all(texts: Iterable[str]) -> ClassificationBatch:
    """Classify many claim strings, returning the results and their distribution."""
    results = tuple(classify_claim_text(text) for text in texts)
    counts: dict[StatementType, int] = dict.fromkeys(StatementType, 0)
    for result in results:
        counts[result.statement_type] += 1
    return ClassificationBatch(classifications=results, type_counts=counts)
