"""How an article presents its subject, measured on eight named dimensions.

This package answers a question that is deliberately *separate* from "is the
article true": it asks how the article is written. The two are independent, and
keeping them apart is the point. A piece can be scrupulously accurate and still
select only the figures that flatter one reading; a piece can be sloppily worded
and still be right. Aleph settles truth elsewhere, speaker-blind, in
:mod:`aleph.claims`; this package settles nothing at all. It measures, quotes the
passages it measured, and hands the reader the arithmetic.

Three commitments are structural rather than advisory:

**There is no aggregate.** :mod:`aleph.framing.profile` exposes eight scores and
no ninth number. A scalar "bias" figure would hide the fact that heavy loaded
language and excellent primary-source grounding are different properties pointing
in different directions, and any such scalar would be read as a left-right
placement — which Aleph does not produce, here or anywhere.

**Every score is openable.** Each dimension returns the sentences it looked at,
the terms it matched, the counts, the formula, the uncertainties it could not
resolve and the observations that point the other way. That is what
:meth:`~aleph.framing.profile.FramingAnalysis.explain` returns, and it returns
data: no verdict, no colour, no adjective.

**Nothing here knows who is speaking.** The dimensions are computed from an
article's text, the primary document, the evidence pool and the rest of the
cluster. Outlet, author, party and speaker identity are not inputs to any of the
eight functions, and none of them can move a score.

The measurements are also *comparative*. ``context_omission`` is computed against
what the rest of the cluster reported, not against an analyst's sense of what
mattered; ``certainty_inflation`` is computed against the modality of the
underlying evidence, not against a preference for hedging; ``selection_asymmetry``
is computed against what the primary document actually contains. An article is
never scored against an imagined ideal article.
"""

from __future__ import annotations

from aleph.framing.profile import (
    LOADED_LANGUAGE_LEXICON,
    PROFILE_VERSION,
    ArticleUnderAnalysis,
    Calculation,
    DimensionResult,
    FramingAnalysis,
    FramingContext,
    LoadedTerm,
    LoadedTermCategory,
    SentenceRef,
    analyse_framing,
    resolve_independence,
)

__all__ = [
    "LOADED_LANGUAGE_LEXICON",
    "PROFILE_VERSION",
    "ArticleUnderAnalysis",
    "Calculation",
    "DimensionResult",
    "FramingAnalysis",
    "FramingContext",
    "LoadedTerm",
    "LoadedTermCategory",
    "SentenceRef",
    "analyse_framing",
    "resolve_independence",
]
