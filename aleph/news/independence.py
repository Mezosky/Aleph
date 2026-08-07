"""How many things were actually observed, behind N things that were published.

This is the module the rest of Aleph leans on hardest, because the single most
reliable way for an automated pipeline to manufacture false confidence is to
count copies. Forty outlets carrying one agency's four hundred words look, to any
naive aggregator, like forty confirmations. They are one observation reproduced
forty times. Volume is a fact about distribution; it is not a fact about the
world, and nothing in Aleph may treat it as one.

So the question this module answers is never "how much coverage is there?" but
**"how many genuinely distinct originals are behind this coverage, and what is
the evidence for that judgement?"** The answer is an
:class:`~aleph.core.models.IndependenceAnalysis`, in which
``total_articles`` is a loudness measure and only
``independent_corroboration_count`` is permitted to raise confidence downstream.

Five independent signals are computed, from scratch, on the standard library
alone — no new dependencies, and deliberately no learned model, because a
syndication finding must be explainable to a reader as "these two texts share
this passage" rather than as a similarity number from a black box.

1. **Near-duplicate detection.** Word shingles are hashed, summarised by a
   from-scratch MinHash, and bucketed by LSH banding to generate candidate pairs
   cheaply; every candidate is then confirmed against the *exact* Jaccard and
   containment of the shingle sets, so the sketch never decides anything on its
   own. Containment matters as much as Jaccard: a syndicated piece is usually a
   *truncated* copy, where Jaccard collapses but containment stays near one.
   A 64-bit SimHash is computed alongside as a second, differently-biased view.

2. **Shared quotations.** Two reporters at the same event get overlapping
   quotations; two outlets copying one file get *identical* ones, including the
   same choice of which sentence to cut. Quotation-set overlap is therefore a
   sharper signal than prose similarity and survives rewriting.

3. **Wire and press-release attribution.** Structural attribution patterns are
   parsed out of the text — bracketed datelines, "with reporting by", "con
   información de", "reproduzido de". The patterns are linguistic, never
   jurisdictional: no agency, outlet or country is named in this module.

4. **Publication-time cascade.** Who published first, and who followed within
   minutes. Two newsrooms do not independently produce near-identical text ninety
   seconds apart. The cascade also gives the chain its direction, which is what
   turns "these are the same" into "this one came from that one".

5. **Shared citations and URLs.** Items pointing at the same primary document or
   dataset are frequently write-ups of one release. That is a weaker signal than
   copying — three outlets reading the same statistical release really did do
   three pieces of work — but it is still one *origin event*, and readiness must
   see it as such.

A sixth signal, ``shared_error``, is supported but never guessed at. Independent
observers do not make the same mistake, so a shared error is the strongest
evidence of a shared origin there is — which is exactly why this module will not
infer one. It fires only from a caller-supplied set of known-erroneous strings
(see ``known_errors``). Aleph does not decide on its own that a figure is wrong
and then use its own guess as proof of syndication.

What the module refuses to do is as load-bearing as what it does. It never reads
the registry's ``typical_independence`` as a verdict — that field is a prior about
a source, and the texts override it. It never treats an outlet's standing as
evidence of originality. And every conclusion carries the measurement that
produced it, because a wrongly asserted chain does real damage in the other
direction: it would suppress genuine corroboration and understate what is known.

Everything here is deterministic. Same articles in, same analysis out, on any
machine, in any process order.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from aleph.core.enums import (
    ArticleType,
    ChainKind,
    ConfidenceEffect,
    ConfidenceFactor,
    Independence,
    SharedOriginKind,
)
from aleph.core.models import (
    Confidence,
    ConfidenceBasis,
    IndependenceAnalysis,
    NewsArticle,
    SharedOriginSignal,
    SyndicationChain,
)

__all__ = [
    "DEFAULT_CONFIG",
    "ArticleFingerprint",
    "IndependenceConfig",
    "IndependenceReport",
    "MinHasher",
    "OriginGroup",
    "PairEvidence",
    "PublicationCascade",
    "WireAttribution",
    "analyse_independence",
    "containment",
    "detailed_analysis",
    "exact_jaccard",
    "explain_pair",
    "extract_quotations",
    "extract_urls",
    "fingerprint_article",
    "hamming_distance",
    "normalise_text",
    "parse_wire_attribution",
    "shingle_hashes",
    "simhash64",
    "tokenise",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IndependenceConfig:
    """Thresholds for every signal, in one inspectable place.

    They are settings, not truths. Each is a judgement about where copying stops
    being plausible coincidence, and each is exposed so a reader who disagrees
    can see the number rather than argue with an outcome. The defaults are
    deliberately *conservative in the direction of independence*: the cost of
    wrongly declaring two originals to be one copy is suppressing real
    corroboration, which is a worse error than counting one observation twice
    and having a reader notice.
    """

    shingle_size: int = 5
    """Words per shingle. Five is long enough that ordinary shared phrasing
    ("the government announced that") does not match, short enough to survive
    light editing."""

    num_permutations: int = 128
    """MinHash sketch width. Standard error of the Jaccard estimate is roughly
    1/sqrt(n), so 128 gives about ±0.09 — plenty for *candidate generation*,
    which is all the sketch is ever used for."""

    lsh_bands: int = 32
    """Bands for LSH candidate bucketing. bands x rows must equal
    num_permutations; 32x4 gives a ~50% detection probability around Jaccard
    0.35, so genuine near-duplicates are recalled generously and false candidates
    are discarded by the exact check that follows."""

    jaccard_duplicate: float = 0.55
    """Exact shingle Jaccard at or above which two texts are near-duplicates."""

    containment_duplicate: float = 0.75
    """Exact containment (shared shingles over the *smaller* set) at or above
    which the smaller text is treated as contained in the larger. Catches the
    common case of a truncated republication, which Jaccard alone misses."""

    simhash_max_distance: int = 6
    """Hamming distance on the 64-bit SimHash below which two texts are
    corroboratively similar. A second opinion, never a sole basis."""

    quote_overlap_min: float = 0.6
    """Jaccard of normalised quotation sets above which the quotation sets are
    'the same set'. Identical choices of what to quote and where to cut are hard
    to arrive at independently."""

    min_shared_quotes: int = 2
    """Shared quotations required before quotation overlap counts at all. One
    shared quote is what a press conference produces; two or more with identical
    cuts is what a shared file produces."""

    min_quote_words: int = 6
    """Quotations shorter than this are ignored. Short quotations collide by
    chance ("we will not accept this") and would fabricate signals."""

    cascade_window_minutes: float = 180.0
    """How long after an original a near-duplicate still counts as following it
    rather than as separate work."""

    same_minute_seconds: float = 90.0
    """Publication gap below which two similar items from different publishers
    are treated as one release rather than two efforts."""

    shared_url_window_hours: float = 48.0
    """Window within which items citing the same URL are treated as covering one
    origin event."""

    min_shared_urls: int = 1
    """Shared external citations required for the shared-origin-event signal."""

    min_tokens_for_similarity: int = 40
    """Below this token count, text similarity is not computed at all. Headlines
    and one-line summaries are too short to distinguish copying from shared
    subject matter, and a similarity score over them would be noise presented as
    evidence."""


DEFAULT_CONFIG: Final[IndependenceConfig] = IndependenceConfig()


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-z]+(?:[.,][0-9]+)*")
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
_URL_RE: Final[re.Pattern[str]] = re.compile(r"https?://[^\s<>\"'\)\]]+", re.IGNORECASE)


def normalise_text(text: str) -> str:
    """Fold text to the form all similarity measures are computed over.

    Accents are stripped, case is dropped, typographic quotes and dashes are
    folded to ASCII and whitespace is collapsed. This is deliberately aggressive:
    a republication that differs only in smart quotes and a stray non-breaking
    space is the same text, and a comparison that says otherwise would let the
    most trivial possible edit defeat the whole analysis.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    folded = folded.translate(_PUNCT_FOLD)
    return _WHITESPACE_RE.sub(" ", folded.lower()).strip()


#: Typographic variants folded to their ASCII equivalents before comparison.
_PUNCT_FOLD: Final[dict[int, str]] = {
    ord("‘"): "'",
    ord("’"): "'",
    ord("‚"): "'",
    ord("“"): '"',
    ord("”"): '"',
    ord("„"): '"',
    ord("«"): '"',
    ord("»"): '"',
    ord("–"): "-",
    ord("—"): "-",
    ord("―"): "-",
    ord("…"): "...",
    ord(" "): " ",
    ord("​"): "",
}


def tokenise(text: str) -> tuple[str, ...]:
    """Split normalised text into comparison tokens.

    Numbers keep their decimal and thousands separators, so ``3.7`` stays one
    token rather than becoming ``3`` and ``7``. Figures are among the most
    diagnostic things two copied texts share, and splitting them would throw that
    away.
    """
    return tuple(_WORD_RE.findall(normalise_text(text)))


def _hash64(value: str) -> int:
    """Deterministic 64-bit fingerprint of a string.

    ``blake2b`` rather than :func:`hash`, which is salted per process: an id or a
    similarity that changed between runs of the same code on the same input would
    make every Aleph bundle undiffable.
    """
    return int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")


def shingle_hashes(tokens: Sequence[str], size: int = 5) -> frozenset[int]:
    """Hash every contiguous ``size``-word window into a set of 64-bit values.

    Word shingles rather than characters because word order is what copying
    preserves and paraphrase destroys, and because character shingles match
    heavily on shared vocabulary — which is exactly what two independent articles
    on one subject legitimately have.
    """
    if size < 1:
        raise ValueError(f"shingle size must be at least 1, got {size}")
    if len(tokens) < size:
        return frozenset({_hash64(" ".join(tokens))}) if tokens else frozenset()
    return frozenset(_hash64(" ".join(tokens[i : i + size])) for i in range(len(tokens) - size + 1))


def exact_jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    """Exact Jaccard similarity of two shingle sets."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    return intersection / (len(a) + len(b) - intersection)


def containment(a: frozenset[int], b: frozenset[int]) -> float:
    """Shared shingles as a fraction of the *smaller* set.

    The measure that catches truncated republication. An outlet that runs the
    first six paragraphs of a two-thousand-word file has copied it completely, but
    the Jaccard of the two is around 0.2 and would pass unnoticed.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


# ---------------------------------------------------------------------------
# MinHash — written out rather than imported
# ---------------------------------------------------------------------------

_MERSENNE_PRIME: Final[int] = (1 << 61) - 1
_HASH_MASK: Final[int] = (1 << 61) - 1


@dataclass(frozen=True, slots=True)
class MinHasher:
    """A deterministic MinHash sketcher with LSH banding.

    Implemented here rather than pulled in as a dependency for two reasons. It is
    forty lines of arithmetic, and — more to the point — the permutation
    coefficients must be a pure function of a fixed seed, so that the candidate
    pairs generated for a document today are the candidate pairs generated for it
    next year. A library seeded from system entropy would make Aleph's output
    quietly irreproducible in a way no test would catch.

    The sketch is only ever used to *propose* pairs. Every proposal is then
    settled by the exact Jaccard and containment of the full shingle sets, which
    this class also keeps available. An approximation may say "look here"; it may
    not say "these are the same".
    """

    num_permutations: int = 128
    bands: int = 32
    seed: str = "aleph.news.independence/minhash/v1"

    @property
    def rows_per_band(self) -> int:
        return self.num_permutations // self.bands

    def _coefficients(self) -> tuple[tuple[int, int], ...]:
        """Derive (a, b) pairs for each permutation from the seed alone."""
        out: list[tuple[int, int]] = []
        for i in range(self.num_permutations):
            digest = hashlib.blake2b(f"{self.seed}:{i}".encode(), digest_size=16).digest()
            a = int.from_bytes(digest[:8], "big") % (_MERSENNE_PRIME - 1) + 1
            b = int.from_bytes(digest[8:], "big") % _MERSENNE_PRIME
            out.append((a, b))
        return tuple(out)

    def signature(self, shingles: Iterable[int]) -> tuple[int, ...]:
        """Compute the MinHash signature of a shingle set.

        An empty set yields the all-maximum signature, which matches nothing —
        the honest answer for a text too short to fingerprint.
        """
        items = list(shingles)
        coefficients = self._coefficients()
        if not items:
            return tuple(_HASH_MASK for _ in coefficients)
        return tuple(
            min(((a * h + b) % _MERSENNE_PRIME) & _HASH_MASK for h in items)
            for a, b in coefficients
        )

    def estimate_jaccard(self, left: Sequence[int], right: Sequence[int]) -> float:
        """Fraction of matching signature positions — an unbiased Jaccard estimate."""
        if not left or len(left) != len(right):
            return 0.0
        return sum(1 for x, y in zip(left, right, strict=True) if x == y) / len(left)

    def bucket_keys(self, signature: Sequence[int]) -> tuple[str, ...]:
        """Per-band bucket keys. Two texts sharing any key are candidates."""
        rows = self.rows_per_band
        keys: list[str] = []
        for band in range(self.bands):
            chunk = signature[band * rows : (band + 1) * rows]
            keys.append(
                f"{band}:"
                + hashlib.blake2b(
                    ",".join(str(v) for v in chunk).encode(), digest_size=8
                ).hexdigest()
            )
        return tuple(keys)


_MINHASHER: Final[MinHasher] = MinHasher()


# ---------------------------------------------------------------------------
# SimHash
# ---------------------------------------------------------------------------


def simhash64(tokens: Sequence[str], *, gram: int = 3) -> int:
    """64-bit SimHash over token n-grams, weighted by frequency.

    Kept alongside MinHash because the two fail differently: MinHash is a set
    measure and ignores how often a phrase occurs, while SimHash is dominated by
    the heaviest-weighted features. Agreement between two measures with different
    biases is worth more than either alone, and disagreement is a reason to
    report the pair as uncertain rather than to pick the flattering number.
    """
    if not tokens:
        return 0
    counts: dict[str, int] = {}
    span = max(1, min(gram, len(tokens)))
    for i in range(len(tokens) - span + 1):
        feature = " ".join(tokens[i : i + span])
        counts[feature] = counts.get(feature, 0) + 1

    accumulator = [0] * 64
    for feature, weight in counts.items():
        h = _hash64(feature)
        for bit in range(64):
            accumulator[bit] += weight if (h >> bit) & 1 else -weight
    value = 0
    for bit in range(64):
        if accumulator[bit] > 0:
            value |= 1 << bit
    return value


def hamming_distance(left: int, right: int) -> int:
    """Number of differing bits between two SimHash values."""
    return ((left ^ right) & ((1 << 64) - 1)).bit_count()


# ---------------------------------------------------------------------------
# Quotations, wire attribution, citations
# ---------------------------------------------------------------------------

_QUOTE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"“([^“”]{8,600})”"),
    re.compile(r"«([^«»]{8,600})»"),
    re.compile(r"„([^„“”]{8,600})[“”]"),
    re.compile(r"\"([^\"]{8,600})\""),
)


def extract_quotations(text: str, *, min_words: int = 6) -> tuple[str, ...]:
    """Pull quoted passages out of running text.

    Straight and typographic quotation marks are both handled, in the several
    conventions different publishing traditions use. Single quotes are
    deliberately *not* matched: apostrophes would produce a flood of spurious
    "quotations" in any language with contractions or possessives, and a signal
    that fires constantly is worse than no signal.

    Passages shorter than ``min_words`` are dropped. Short quotations collide by
    coincidence, and coincidence presented as evidence of syndication would let
    this module suppress real corroboration.
    """
    found: list[str] = []
    seen: set[str] = set()
    for pattern in _QUOTE_PATTERNS:
        for match in pattern.finditer(text):
            candidate = match.group(1).strip()
            if len(candidate.split()) < min_words:
                continue
            key = normalise_text(candidate)
            if key and key not in seen:
                seen.add(key)
                found.append(candidate)
    return tuple(found)


def normalise_quotation(text: str) -> str:
    """Canonical form of a quotation, for set comparison.

    Trailing ellipses and attribution tails are stripped so that the same
    sentence cut at the same place matches even when one outlet marked the cut
    and another did not.
    """
    normalised = normalise_text(text).strip(" .,;:'\"-")
    normalised = re.sub(r"\.{3,}", " ", normalised)
    return _WHITESPACE_RE.sub(" ", normalised).strip()


@dataclass(frozen=True, slots=True)
class WireAttribution:
    """A parsed statement that an item's material came from somewhere else.

    ``agency`` is whatever string the text itself named. This module neither
    knows nor cares which agencies exist: the patterns are linguistic, and a
    hard-coded list of agency names would make the module jurisdiction-specific
    and would silently fail on the first market it had not been told about.
    """

    agency: str
    """The attributed origin, verbatim from the text."""
    marker: str
    """The matched phrase, quoted so a reader can check the parse."""
    pattern: str
    """Which structural pattern fired, for debugging a false positive."""

    @property
    def slug(self) -> str:
        """Comparison key. Two items attributing to the same string share an origin."""
        return normalise_text(self.agency)


# Structural attribution patterns. Each names a linguistic construction, not an
# organisation. Ordered most-specific first; the first match wins.
_WIRE_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "dateline_parenthetical",
        re.compile(
            r"^\s*[A-ZÁÉÍÓÚÑÜ][A-Za-zÁÉÍÓÚÑÜáéíóúñü .'\-]{1,40},\s*"
            r"\d{1,2}\s*[a-zA-Zé]{0,12}\.?\s*\(([^)]{2,40})\)",
        ),
    ),
    (
        "leading_parenthetical",
        re.compile(r"^\s*\(([A-Za-zÁÉÍÓÚÑÜ][^)]{1,39})\)\s*[-–—:]"),
    ),
    (
        "attribution_phrase",
        re.compile(
            r"(?:with\s+reporting\s+by|reporting\s+by|reported\s+by"
            r"|originally\s+published\s+(?:by|in|at)|first\s+reported\s+by"
            r"|republished\s+from|syndicated\s+(?:from|by)"
            r"|con\s+informaci[oó]n\s+de|informaci[oó]n\s+de"
            r"|seg[uú]n\s+inform[oó]|public[oó]\s+originalmente"
            r"|reproduzido\s+de|com\s+informa[cç][oõ]es\s+d[eo]"
            r"|avec\s+(?:des\s+)?informations\s+de|d'apr[eè]s\s+un\s+article\s+de)"
            r"\s+([A-Za-zÁÉÍÓÚÑÜáéíóúñü0-9 .'&\-]{2,40})",
            re.IGNORECASE,
        ),
    ),
    (
        "credit_suffix",
        re.compile(r"[/–—-]\s*(?:agencia|agency|wire)\s+([A-Za-z0-9 .'&-]{2,30})", re.I),
    ),
)


def parse_wire_attribution(
    text: str, *, extra_patterns: Sequence[tuple[str, re.Pattern[str]]] = ()
) -> WireAttribution | None:
    """Find an explicit attribution of an item's material to another source.

    Returns the first structural match, or ``None``. A returned attribution is a
    strong signal but not a conclusion on its own: an article that credits an
    agency for one paragraph and reports the rest itself is still partly
    original, which is why the caller combines this with text similarity before
    declaring a chain.

    Args:
        text: The article text to parse.
        extra_patterns: Caller-supplied ``(name, compiled_pattern)`` pairs whose
            first capturing group is the attributed origin. The extension point
            exists so a deployment can teach the parser a local convention
            without this module acquiring knowledge of a particular market.
    """
    for name, pattern in (*extra_patterns, *_WIRE_PATTERNS):
        match = pattern.search(text)
        if match:
            agency = match.group(1).strip(" .,-–—")
            if agency and len(agency) >= 2:
                return WireAttribution(agency=agency, marker=match.group(0).strip(), pattern=name)
    return None


def extract_urls(text: str) -> frozenset[str]:
    """Pull external citations out of text, normalised for comparison.

    Scheme, ``www.`` prefix, tracking query and trailing slash are dropped, so
    the same document cited through two different share links compares equal.
    Tracking parameters in particular would otherwise make every citation unique
    and destroy the signal entirely.
    """
    out: set[str] = set()
    for raw in _URL_RE.findall(text):
        cleaned = raw.rstrip(".,;:)’\"'")
        cleaned = re.sub(r"^https?://", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^www\.", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.split("#", 1)[0]
        cleaned = re.sub(r"[?&](utm_[^=]+|fbclid|gclid|mc_cid|mc_eid)=[^&]*", "", cleaned)
        cleaned = cleaned.rstrip("?&/").lower()
        if cleaned:
            out.add(cleaned)
    return frozenset(out)


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArticleFingerprint:
    """Everything about one item that bears on whether it is a copy.

    ``text_basis`` is the field to read first and is the reason this is a class
    rather than a tuple of numbers. When no body text is available, similarity is
    measured over a headline, a dek and Aleph's own neutral summary — which is a
    much weaker basis than full text, and a reader is entitled to know that a
    syndication finding rests on it. Any confidence derived from this fingerprint
    is capped accordingly.
    """

    article_id: str
    publisher_id: str
    published_at: datetime | None
    time_precise: bool
    """False when the source stated only a calendar date. A date-only item is
    normalised to midnight UTC for ordering, which would make two same-day items
    look simultaneous — so the cascade and same-minute signals refuse to fire on
    it. Coarse metadata must produce no finding, not a confident wrong one."""
    language: str | None
    article_type: ArticleType
    declared_independence: Independence
    declared_origin_id: str | None
    """The article's own ``derived_from_article_id``, when it names one. An
    explicit claim of derivation is honoured over anything inferred."""
    token_count: int
    text_basis: str
    """Which fields the similarity measures were computed over."""
    body_available: bool
    shingles: frozenset[int]
    minhash: tuple[int, ...]
    simhash: int
    quotations: frozenset[str]
    """Normalised quotations long enough to be diagnostic."""
    urls: frozenset[str]
    wire: WireAttribution | None
    grounding_refs: frozenset[str]
    error_markers: frozenset[str]
    """Known-erroneous strings this item contains, supplied by the caller. Never
    inferred: see the module docstring."""

    @property
    def comparable(self) -> bool:
        """Whether the text is long enough for similarity to mean anything."""
        return self.token_count >= DEFAULT_CONFIG.min_tokens_for_similarity


def fingerprint_article(
    article: NewsArticle,
    *,
    body: str | None = None,
    config: IndependenceConfig = DEFAULT_CONFIG,
    known_errors: Mapping[str, str] | None = None,
    extra_wire_patterns: Sequence[tuple[str, re.Pattern[str]]] = (),
) -> ArticleFingerprint:
    """Compute every signal for one article.

    Args:
        article: The item to fingerprint.
        body: Full text, when it was retrieved. Its absence is recorded rather
            than worked around: ``text_basis`` will say so and confidence
            downstream is capped.
        config: Thresholds.
        known_errors: Strings known to be erroneous, mapped to a note about the
            correction. Only these can produce a ``shared_error`` signal.
        extra_wire_patterns: Additional attribution patterns.
    """
    parts: list[str] = [article.headline]
    basis: list[str] = ["headline"]
    if article.dek:
        parts.append(article.dek)
        basis.append("dek")
    if body:
        parts.append(body)
        basis.append("body")
    else:
        parts.append(article.neutral_summary)
        basis.append("neutral_summary")
    quote_texts = [q.text for q in article.quotations]
    if quote_texts:
        parts.extend(quote_texts)
        basis.append("quotations")

    combined = "\n".join(parts)
    tokens = tokenise(combined)
    shingles = shingle_hashes(tokens, config.shingle_size)

    quotations = {
        normalise_quotation(q.text)
        for q in article.quotations
        if len(q.text.split()) >= config.min_quote_words
    }
    quotations.update(
        normalise_quotation(q)
        for q in extract_quotations(combined, min_words=config.min_quote_words)
    )
    quotations.discard("")

    urls = set(extract_urls(combined))
    if article.url:
        # An item's own address is not a citation of anything.
        urls -= extract_urls(article.url)

    markers = {
        marker
        for marker in (known_errors or {})
        if normalise_text(marker) and normalise_text(marker) in normalise_text(combined)
    }

    return ArticleFingerprint(
        article_id=article.id,
        publisher_id=article.publisher.id,
        published_at=_parse_instant(article.published_at) or _parse_instant(article.retrieved_at),
        time_precise=_has_time_of_day(article.published_at),
        language=article.language,
        article_type=article.article_type,
        declared_independence=article.independence,
        declared_origin_id=article.derived_from_article_id,
        token_count=len(tokens),
        text_basis="+".join(basis),
        body_available=bool(body) or article.body_available,
        shingles=shingles,
        minhash=_MINHASHER.signature(shingles) if shingles else (),
        simhash=simhash64(tokens),
        quotations=frozenset(quotations),
        urls=frozenset(urls),
        wire=parse_wire_attribution(combined, extra_patterns=extra_wire_patterns),
        grounding_refs=frozenset(g.ref for g in article.primary_source_grounding),
        error_markers=frozenset(markers),
    )


def _parse_instant(value: str | None) -> datetime | None:
    """Parse an ISO date or UTC timestamp into an aware datetime.

    A plain date becomes midnight UTC. That is a coarsening, and it is why the
    same-minute signal requires real timestamps: a cascade cannot be read off
    date-only metadata, and this module does not pretend otherwise.
    """
    if not value:
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text[:-1]).replace(tzinfo=UTC)
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _has_time_of_day(value: str | None) -> bool:
    """Whether a published_at string carried a time, not only a calendar date."""
    return bool(value) and "T" in value


# ---------------------------------------------------------------------------
# Pairwise evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PairEvidence:
    """Every measurement taken on one pair of articles, and what it implies.

    Returned to callers and rendered by the UI, because "these two are the same
    story" is a claim Aleph makes about other people's work and it must be
    checkable. ``signals`` names which thresholds were crossed; ``shared_material``
    quotes the specific text.
    """

    left_id: str
    right_id: str
    jaccard: float
    containment: float
    minhash_estimate: float
    simhash_distance: int
    shared_quotes: tuple[str, ...]
    quote_overlap: float
    shared_urls: tuple[str, ...]
    shared_errors: tuple[str, ...]
    same_wire_agency: str | None
    seconds_apart: float | None
    signals: tuple[SharedOriginKind, ...]
    shared_material: str
    comparable: bool
    """False when at least one text was too short to measure. The pair may still
    carry a quotation or citation signal; it simply has no similarity number."""

    @property
    def is_shared_origin(self) -> bool:
        """Whether any signal fired at all."""
        return bool(self.signals)

    @property
    def is_reproduction(self) -> bool:
        """Whether the evidence supports one item being a copy of the other.

        Distinguished from :attr:`is_shared_origin` because sharing an origin
        *event* — two write-ups of one dataset release — is not the same as
        sharing an origin *text*, and only the second collapses to a single
        observation of the underlying facts.
        """
        return bool(
            {
                SharedOriginKind.IDENTICAL_PHRASING,
                SharedOriginKind.IDENTICAL_QUOTE_SET,
                SharedOriginKind.SAME_WIRE_SLUG,
                SharedOriginKind.SAME_PRESS_RELEASE,
                SharedOriginKind.SHARED_ERROR,
            }
            & set(self.signals)
        )


def explain_pair(
    left: ArticleFingerprint,
    right: ArticleFingerprint,
    *,
    config: IndependenceConfig = DEFAULT_CONFIG,
) -> PairEvidence:
    """Measure one pair and report which shared-origin signals fired.

    Every threshold comparison in the module happens here, in one place, so the
    rules are readable end to end rather than scattered through the clustering
    loop.
    """
    comparable = (
        left.token_count >= config.min_tokens_for_similarity
        and right.token_count >= config.min_tokens_for_similarity
    )
    jac = exact_jaccard(left.shingles, right.shingles) if comparable else 0.0
    cont = containment(left.shingles, right.shingles) if comparable else 0.0
    estimate = (
        _MINHASHER.estimate_jaccard(left.minhash, right.minhash)
        if comparable and left.minhash and right.minhash
        else 0.0
    )
    sim_distance = hamming_distance(left.simhash, right.simhash) if comparable else 64

    shared_quotes = tuple(sorted(left.quotations & right.quotations))
    quote_union = len(left.quotations | right.quotations)
    quote_overlap = len(left.quotations & right.quotations) / quote_union if quote_union else 0.0

    shared_urls = tuple(sorted(left.urls & right.urls))
    shared_errors = tuple(sorted(left.error_markers & right.error_markers))

    same_agency: str | None = None
    if left.wire and right.wire and left.wire.slug == right.wire.slug:
        same_agency = left.wire.agency

    seconds_apart: float | None = None
    if left.published_at and right.published_at:
        seconds_apart = abs((left.published_at - right.published_at).total_seconds())
    minute_resolvable = left.time_precise and right.time_precise

    signals: list[SharedOriginKind] = []
    material: list[str] = []

    if comparable and (jac >= config.jaccard_duplicate or cont >= config.containment_duplicate):
        signals.append(SharedOriginKind.IDENTICAL_PHRASING)
        material.append(
            f"word-shingle Jaccard {jac:.2f}, containment {cont:.2f} "
            f"(SimHash distance {sim_distance}) over {left.text_basis}/{right.text_basis}"
        )
    elif comparable and sim_distance <= config.simhash_max_distance and jac > 0.25:
        signals.append(SharedOriginKind.IDENTICAL_PHRASING)
        material.append(
            f"SimHash distance {sim_distance} with Jaccard {jac:.2f}: heavily edited reuse"
        )

    if len(shared_quotes) >= config.min_shared_quotes and quote_overlap >= config.quote_overlap_min:
        signals.append(SharedOriginKind.IDENTICAL_QUOTE_SET)
        material.append(
            f"{len(shared_quotes)} identical quotations (set overlap {quote_overlap:.2f}), "
            f'first: "{shared_quotes[0][:160]}"'
        )

    if same_agency is not None:
        signals.append(SharedOriginKind.SAME_WIRE_SLUG)
        material.append(
            f"both attribute their material to the same origin, named in the text as "
            f'"{same_agency}"'
        )

    if (
        ArticleType.PRESS_RELEASE in (left.article_type, right.article_type)
        and shared_quotes
        and left.publisher_id != right.publisher_id
    ):
        signals.append(SharedOriginKind.SAME_PRESS_RELEASE)
        material.append(
            f"one item is a press release and {len(shared_quotes)} of its quotations appear "
            "verbatim in the other"
        )

    if shared_errors:
        signals.append(SharedOriginKind.SHARED_ERROR)
        material.append(
            "both reproduce the same known-erroneous text: "
            + "; ".join(f'"{e}"' for e in shared_errors[:3])
            + " — independent observers do not make the same mistake"
        )

    if (
        len(shared_urls) >= config.min_shared_urls
        and seconds_apart is not None
        and seconds_apart <= config.shared_url_window_hours * 3600
        and SharedOriginKind.IDENTICAL_PHRASING not in signals
    ):
        signals.append(SharedOriginKind.SAME_DATASET_RELEASE)
        material.append(
            f"both cite {len(shared_urls)} of the same source(s) within "
            f"{seconds_apart / 3600:.1f}h — one origin event, written up separately"
        )

    if (
        minute_resolvable
        and seconds_apart is not None
        and seconds_apart <= config.same_minute_seconds
        and left.publisher_id != right.publisher_id
        and (signals or shared_quotes)
    ):
        signals.append(SharedOriginKind.SAME_PUBLICATION_MINUTE)
        material.append(
            f"published {seconds_apart:.0f}s apart by different publishers: a distribution "
            "event, not two independent efforts"
        )

    return PairEvidence(
        left_id=left.article_id,
        right_id=right.article_id,
        jaccard=round(jac, 4),
        containment=round(cont, 4),
        minhash_estimate=round(estimate, 4),
        simhash_distance=sim_distance,
        shared_quotes=shared_quotes,
        quote_overlap=round(quote_overlap, 4),
        shared_urls=shared_urls,
        shared_errors=shared_errors,
        same_wire_agency=same_agency,
        seconds_apart=seconds_apart,
        signals=tuple(dict.fromkeys(signals)),
        shared_material="; ".join(material),
        comparable=comparable,
    )


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


class _UnionFind:
    """Minimal disjoint-set over article ids, with deterministic roots."""

    def __init__(self, items: Iterable[str]) -> None:
        self._parent: dict[str, str] = {item: item for item in items}

    def find(self, item: str) -> str:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a == b:
            return
        # Smaller id wins, so the partition does not depend on merge order.
        if a > b:
            a, b = b, a
        self._parent[b] = a

    def groups(self) -> list[list[str]]:
        buckets: dict[str, list[str]] = {}
        for item in sorted(self._parent):
            buckets.setdefault(self.find(item), []).append(item)
        return [buckets[key] for key in sorted(buckets)]


@dataclass(frozen=True, slots=True)
class PublicationCascade:
    """Who published first, and how far behind everyone else was.

    Lead times are the most legible form the finding takes for a reader: "the
    other eleven appeared between four and ninety minutes later" says more about
    what happened than any similarity coefficient.
    """

    origin_article_id: str
    origin_published_at: datetime | None
    followers: tuple[tuple[str, float | None], ...]
    """``(article_id, minutes_after_origin)``. ``None`` when the item carried no
    usable publication time — recorded as unknown rather than assumed to be zero."""

    def describe(self) -> str:
        known = [m for _, m in self.followers if m is not None]
        if not known:
            return f"{len(self.followers)} later item(s), publication times unavailable"
        return (
            f"{len(self.followers)} item(s) followed between {min(known):.0f} and "
            f"{max(known):.0f} minutes after the earliest"
        )


@dataclass(frozen=True, slots=True)
class OriginGroup:
    """One set of items that trace back to a single origin.

    ``origin_id`` is the item Aleph believes came first. It is chosen by explicit
    derivation claim, then publication time, then artefact type — never by which
    publisher is better known, which would reintroduce prestige through the back
    door of attribution.
    """

    origin_id: str
    member_ids: tuple[str, ...]
    origin_publisher_id: str
    chain_kind: ChainKind
    pair_evidence: tuple[PairEvidence, ...]
    cascade: PublicationCascade | None
    reproduction: bool
    """True when the members share an origin *text*; false when they merely share
    an origin *event*, such as one dataset release written up independently."""

    @property
    def downstream_ids(self) -> tuple[str, ...]:
        return tuple(i for i in self.member_ids if i != self.origin_id)


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IndependenceReport:
    """The full working, with the publishable summary inside it.

    :attr:`analysis` is what goes into a cluster and the bundle. Everything else
    is the audit trail: the fingerprints, every pair that fired a signal, and the
    resulting groups. A syndication finding is an assertion about someone else's
    journalism, so the measurements behind it are kept rather than discarded.
    """

    analysis: IndependenceAnalysis
    fingerprints: tuple[ArticleFingerprint, ...]
    pairs: tuple[PairEvidence, ...]
    groups: tuple[OriginGroup, ...]
    config: IndependenceConfig = DEFAULT_CONFIG
    text_basis_note: str = ""


def analyse_independence(
    articles: Sequence[NewsArticle],
    *,
    bodies: Mapping[str, str] | None = None,
    known_errors: Mapping[str, str] | None = None,
    config: IndependenceConfig = DEFAULT_CONFIG,
    extra_wire_patterns: Sequence[tuple[str, re.Pattern[str]]] = (),
) -> IndependenceAnalysis:
    """Count how many distinct originals lie behind a set of published items.

    The headline result. ``total_articles`` is how loud the coverage was;
    ``distinct_original_sources`` is how much was actually observed; and only
    ``independent_corroboration_count`` may be used to raise confidence anywhere
    downstream.

    Args:
        articles: The items to analyse. Order does not affect the result.
        bodies: Full text keyed by article id, where it was retrieved. Absence is
            recorded, not worked around.
        known_errors: Strings known to be erroneous, keyed to a note. The only
            way a ``shared_error`` signal can fire; nothing is inferred.
        config: Thresholds.
        extra_wire_patterns: Additional attribution patterns.
    """
    return detailed_analysis(
        articles,
        bodies=bodies,
        known_errors=known_errors,
        config=config,
        extra_wire_patterns=extra_wire_patterns,
    ).analysis


def detailed_analysis(
    articles: Sequence[NewsArticle],
    *,
    bodies: Mapping[str, str] | None = None,
    known_errors: Mapping[str, str] | None = None,
    config: IndependenceConfig = DEFAULT_CONFIG,
    extra_wire_patterns: Sequence[tuple[str, re.Pattern[str]]] = (),
) -> IndependenceReport:
    """As :func:`analyse_independence`, but returning the whole audit trail."""
    fingerprints = tuple(
        fingerprint_article(
            article,
            body=(bodies or {}).get(article.id),
            config=config,
            known_errors=known_errors,
            extra_wire_patterns=extra_wire_patterns,
        )
        for article in sorted(articles, key=lambda a: a.id)
    )
    by_id = {fp.article_id: fp for fp in fingerprints}

    pairs = _measure_pairs(fingerprints, config=config)
    groups = _build_groups(fingerprints, pairs, config=config)

    chains = [
        _chain_for(group, by_id, len(fingerprints)) for group in groups if group.downstream_ids
    ]
    signals = _signal_models(pairs)

    origin_ids = [group.origin_id for group in groups]
    distinct_sources = len({by_id[i].publisher_id for i in origin_ids})
    corroborating = _corroborating_publishers(origin_ids, by_id)

    bodies_present = sum(1 for fp in fingerprints if fp.body_available)
    basis_note = (
        f"similarity computed with full text for {bodies_present} of {len(fingerprints)} items"
        if fingerprints
        else "no items"
    )

    analysis = IndependenceAnalysis(
        distinct_original_sources=distinct_sources,
        total_articles=len(fingerprints),
        syndication_chains=[chain for chain in chains if chain is not None],
        shared_origin_evidence=signals,
        independent_corroboration_count=min(len(corroborating), distinct_sources),
        note=_analysis_note(
            total=len(fingerprints),
            distinct=distinct_sources,
            corroborating=corroborating,
            groups=groups,
            basis_note=basis_note,
        ),
    )
    return IndependenceReport(
        analysis=analysis,
        fingerprints=fingerprints,
        pairs=pairs,
        groups=groups,
        config=config,
        text_basis_note=basis_note,
    )


def _measure_pairs(
    fingerprints: Sequence[ArticleFingerprint], *, config: IndependenceConfig
) -> tuple[PairEvidence, ...]:
    """Measure every pair worth measuring, and no others.

    Candidates come from three cheap inverted indexes — MinHash LSH buckets,
    shared quotations, shared citations — plus every pair sharing a wire
    attribution or a known error. Anything not proposed by one of those cannot
    fire a signal, so skipping it costs nothing and the analysis stays linear in
    practice rather than quadratic. For small sets the union is simply all pairs.
    """
    candidates: set[tuple[str, str]] = set()
    by_id = {fp.article_id: fp for fp in fingerprints}

    def index(key_of) -> None:  # type: ignore[no-untyped-def]
        buckets: dict[str, list[str]] = {}
        for fp in fingerprints:
            for key in key_of(fp):
                buckets.setdefault(key, []).append(fp.article_id)
        for members in buckets.values():
            if len(members) < 2 or len(members) > 400:
                continue
            ordered = sorted(members)
            for i, left in enumerate(ordered):
                for right in ordered[i + 1 :]:
                    candidates.add((left, right))

    index(lambda fp: _MINHASHER.bucket_keys(fp.minhash) if fp.minhash else ())
    index(lambda fp: (f"q:{q}" for q in fp.quotations))
    index(lambda fp: (f"u:{u}" for u in fp.urls))
    index(lambda fp: (f"w:{fp.wire.slug}",) if fp.wire else ())
    index(lambda fp: (f"e:{e}" for e in fp.error_markers))
    index(lambda fp: (f"g:{g}" for g in fp.grounding_refs))

    measured: list[PairEvidence] = []
    for left_id, right_id in sorted(candidates):
        evidence = explain_pair(by_id[left_id], by_id[right_id], config=config)
        if evidence.is_shared_origin:
            measured.append(evidence)
    return tuple(measured)


def _build_groups(
    fingerprints: Sequence[ArticleFingerprint],
    pairs: Sequence[PairEvidence],
    *,
    config: IndependenceConfig,
) -> tuple[OriginGroup, ...]:
    """Collapse the pair graph into origin groups, one per distinct original.

    Only *reproduction* signals merge. Two independent write-ups of the same
    dataset release share an origin event and are recorded as such in the
    evidence, but they are not merged into one original, because two newsrooms
    reading one release really did produce two readings — and merging them would
    understate what is known, which is the error this module must not make.
    """
    union = _UnionFind(fp.article_id for fp in fingerprints)
    by_id = {fp.article_id: fp for fp in fingerprints}

    # An explicit derivation claim outranks anything measured.
    for fp in fingerprints:
        if fp.declared_origin_id and fp.declared_origin_id in by_id:
            union.union(fp.article_id, fp.declared_origin_id)

    merging_pairs = [p for p in pairs if p.is_reproduction]
    for pair in merging_pairs:
        if pair.seconds_apart is not None and pair.seconds_apart > (
            config.cascade_window_minutes * 60
        ):
            # Same text months apart is a re-run or an anniversary piece, not a
            # cascade. Still recorded as evidence; simply not merged on time.
            if SharedOriginKind.SHARED_ERROR not in pair.signals:
                continue
        union.union(pair.left_id, pair.right_id)

    pairs_by_group: dict[str, list[PairEvidence]] = {}
    groups: list[OriginGroup] = []
    for members in union.groups():
        member_set = set(members)
        relevant = [p for p in pairs if p.left_id in member_set and p.right_id in member_set]
        pairs_by_group[members[0]] = relevant
        origin_id = _choose_origin(members, by_id)
        groups.append(
            OriginGroup(
                origin_id=origin_id,
                member_ids=tuple(members),
                origin_publisher_id=by_id[origin_id].publisher_id,
                chain_kind=_chain_kind(members, relevant, by_id),
                pair_evidence=tuple(relevant),
                cascade=_cascade(origin_id, members, by_id),
                reproduction=any(p.is_reproduction for p in relevant),
            )
        )
    return tuple(groups)


def _choose_origin(members: Sequence[str], by_id: Mapping[str, ArticleFingerprint]) -> str:
    """Pick the item a group came from.

    The ordering is: an explicit derivation root, then earliest publication, then
    artefact type (a wire item or a press release is upstream of the coverage
    that carries it), then a declared claim of original reporting, then the id as
    a deterministic tie-break.

    Note what is absent: no step consults the publisher. Choosing the
    best-regarded outlet as the origin would attribute originality by reputation,
    which is precisely the substitution this module exists to prevent.
    """
    member_set = set(members)
    roots = [
        m
        for m in members
        if not by_id[m].declared_origin_id or by_id[m].declared_origin_id not in member_set
    ]
    pool = roots or list(members)

    type_rank = {ArticleType.PRESS_RELEASE: 0, ArticleType.WIRE: 0}
    independence_rank = {
        Independence.ORIGINAL_REPORTING: 0,
        Independence.UNKNOWN: 1,
        Independence.SYNDICATED: 2,
        Independence.DERIVATIVE: 2,
        Independence.AGGREGATED: 3,
    }

    def key(article_id: str) -> tuple[float, int, int, str]:
        fp = by_id[article_id]
        when = fp.published_at.timestamp() if fp.published_at else float("inf")
        return (
            when,
            type_rank.get(fp.article_type, 1),
            independence_rank.get(fp.declared_independence, 1),
            article_id,
        )

    return min(pool, key=key)


def _chain_kind(
    members: Sequence[str],
    pairs: Sequence[PairEvidence],
    by_id: Mapping[str, ArticleFingerprint],
) -> ChainKind:
    """Name how the downstream items came to reproduce the original."""
    signals = {s for p in pairs for s in p.signals}
    types = {by_id[m].article_type for m in members}
    languages = {by_id[m].language for m in members if by_id[m].language}

    if SharedOriginKind.SAME_WIRE_SLUG in signals or ArticleType.WIRE in types:
        return ChainKind.WIRE_REDISTRIBUTION
    if SharedOriginKind.SAME_PRESS_RELEASE in signals or ArticleType.PRESS_RELEASE in types:
        return ChainKind.PRESS_RELEASE_PICKUP
    if len(languages) > 1 and SharedOriginKind.IDENTICAL_QUOTE_SET in signals:
        return ChainKind.TRANSLATION
    if SharedOriginKind.IDENTICAL_PHRASING in signals:
        return ChainKind.VERBATIM_REUSE
    if any(by_id[m].declared_independence is Independence.AGGREGATED for m in members):
        return ChainKind.AGGREGATION
    return ChainKind.UNKNOWN


def _cascade(
    origin_id: str, members: Sequence[str], by_id: Mapping[str, ArticleFingerprint]
) -> PublicationCascade | None:
    """Lead times from the origin to everything that followed it."""
    if len(members) < 2:
        return None
    origin = by_id[origin_id]
    origin_at = origin.published_at
    followers: list[tuple[str, float | None]] = []
    for member in members:
        if member == origin_id:
            continue
        follower = by_id[member]
        at = follower.published_at
        # Minute-level lead times are reported only when both items carried a
        # real time. Deriving "published 0 minutes apart" from two calendar dates
        # would be an artefact of normalisation presented as an observation.
        resolvable = at and origin_at and origin.time_precise and follower.time_precise
        minutes = (at - origin_at).total_seconds() / 60.0 if resolvable else None
        followers.append((member, minutes))
    followers.sort(key=lambda item: (item[1] if item[1] is not None else float("inf"), item[0]))
    return PublicationCascade(
        origin_article_id=origin_id, origin_published_at=origin_at, followers=tuple(followers)
    )


def _chain_for(
    group: OriginGroup, by_id: Mapping[str, ArticleFingerprint], corpus_size: int
) -> SyndicationChain | None:
    """Render one origin group as a publishable syndication chain.

    Groups that share only an origin *event* are deliberately not rendered as
    chains: asserting a chain where none exists would collapse genuine
    corroboration, and the shared-origin evidence already records the overlap
    honestly without over-claiming.
    """
    if not group.downstream_ids or not group.reproduction:
        return None

    lines: list[str] = []
    for pair in group.pair_evidence[:4]:
        if pair.is_reproduction:
            lines.append(f"{pair.left_id} / {pair.right_id}: {pair.shared_material}")
    if group.cascade:
        lines.append(group.cascade.describe())
    basis = {by_id[m].text_basis for m in group.member_ids}
    lines.append("measured over: " + ", ".join(sorted(basis)))

    full_text = all(by_id[m].body_available for m in group.member_ids)
    quote_backed = any(
        SharedOriginKind.IDENTICAL_QUOTE_SET in p.signals for p in group.pair_evidence
    )
    error_backed = any(SharedOriginKind.SHARED_ERROR in p.signals for p in group.pair_evidence)

    score = 0.5
    score += 0.2 if full_text else 0.0
    score += 0.15 if quote_backed else 0.0
    score += 0.25 if error_backed else 0.0
    score += 0.05 if group.chain_kind is not ChainKind.UNKNOWN else -0.1
    evidence_confidence = round(max(0.05, min(0.98, score)), 3)

    basis_entries = [
        ConfidenceBasis(
            factor=ConfidenceFactor.SOURCE_INDEPENDENCE,
            effect=ConfidenceEffect.RAISES if group.reproduction else ConfidenceEffect.NEUTRAL,
            note=(
                f"{len(group.downstream_ids)} of {corpus_size} items in this set reproduce "
                f"{group.origin_id} rather than observing independently"
            ),
        ),
        ConfidenceBasis(
            factor=ConfidenceFactor.RETRIEVAL_COMPLETENESS,
            effect=ConfidenceEffect.RAISES if full_text else ConfidenceEffect.LOWERS,
            note=(
                "full text was available for every member"
                if full_text
                else "at least one item was compared on headline and summary only, which is a "
                "weaker basis for a reproduction finding"
            ),
        ),
    ]

    return SyndicationChain(
        origin_article_id=group.origin_id,
        downstream_article_ids=list(group.downstream_ids),
        chain_kind=group.chain_kind,
        evidence=" | ".join(lines) if lines else "shared-origin signals fired on every pair",
        confidence=Confidence(
            evidence_confidence=evidence_confidence,
            basis=basis_entries,
            limiting_factor=(
                None
                if full_text
                else "similarity was measured without full article text for at least one member"
            ),
        ),
    )


def _signal_models(pairs: Sequence[PairEvidence]) -> list[SharedOriginSignal]:
    """Group the pairwise measurements into one signal per kind per article set.

    Emitting one signal per pair would bury a reader in near-identical rows; a
    reader wants "these six items share this quotation set", with the quotation.
    """
    grouped: dict[tuple[SharedOriginKind, str], list[PairEvidence]] = {}
    for pair in pairs:
        for signal in pair.signals:
            grouped.setdefault((signal, ""), []).append(pair)

    out: list[SharedOriginSignal] = []
    for (kind, _), members in sorted(grouped.items(), key=lambda item: item[0][0].value):
        article_ids = sorted({pid for pair in members for pid in (pair.left_id, pair.right_id)})
        if len(article_ids) < 2:
            continue
        exemplar = max(members, key=lambda p: (p.jaccard, p.quote_overlap, p.left_id))
        similarity = _signal_similarity(kind, members)
        out.append(
            SharedOriginSignal(
                kind=kind,
                article_ids=article_ids,
                similarity=similarity,
                detail=_signal_detail(kind, members, exemplar),
            )
        )
    return out


def _signal_similarity(kind: SharedOriginKind, members: Sequence[PairEvidence]) -> float | None:
    """The number that best represents this signal, or ``None`` where none does.

    A wire attribution or a shared error is categorical: there is no meaningful
    similarity coefficient, and inventing one would dress a yes/no observation up
    as a measurement.
    """
    if kind is SharedOriginKind.IDENTICAL_PHRASING:
        return round(max(max(p.jaccard, p.containment) for p in members), 4)
    if kind is SharedOriginKind.IDENTICAL_QUOTE_SET:
        return round(max(p.quote_overlap for p in members), 4)
    return None


def _signal_detail(
    kind: SharedOriginKind, members: Sequence[PairEvidence], exemplar: PairEvidence
) -> str:
    """The specific shared material, quoted where quoting is possible."""
    count = len(members)
    if kind is SharedOriginKind.SHARED_ERROR:
        return (
            f"{count} pair(s) reproduce the same known-erroneous text: "
            + "; ".join(f'"{e}"' for e in exemplar.shared_errors[:3])
            + ". Independent observers do not make the same mistake, so this is the "
            "strongest available evidence of a shared origin."
        )
    if kind is SharedOriginKind.IDENTICAL_QUOTE_SET and exemplar.shared_quotes:
        return (
            f"{count} pair(s) carry the same quotations, cut at the same points; "
            f'e.g. "{exemplar.shared_quotes[0][:200]}"'
        )
    if kind is SharedOriginKind.SAME_WIRE_SLUG and exemplar.same_wire_agency:
        return (
            f"{count} pair(s) attribute their material to the same origin, named as "
            f'"{exemplar.same_wire_agency}" in the text'
        )
    if kind is SharedOriginKind.IDENTICAL_PHRASING:
        return (
            f"{count} pair(s) share word-for-word passages: peak shingle Jaccard "
            f"{exemplar.jaccard:.2f} with containment {exemplar.containment:.2f} "
            f"(SimHash distance {exemplar.simhash_distance}), measured over "
            f"{exemplar.left_id} and {exemplar.right_id}. Containment above Jaccard means "
            "the shorter item is a truncated copy of the longer."
        )
    if kind is SharedOriginKind.SAME_DATASET_RELEASE and exemplar.shared_urls:
        return (
            f"{count} pair(s) cite the same source(s) within the release window; e.g. "
            f"{exemplar.shared_urls[0][:160]}. These are separate write-ups of ONE origin "
            "event: they corroborate each other's reading of the release, not the release."
        )
    if kind is SharedOriginKind.SAME_PUBLICATION_MINUTE and exemplar.seconds_apart is not None:
        return (
            f"{count} pair(s) published within {exemplar.seconds_apart:.0f}s of each other by "
            "different publishers while carrying the same material. Two newsrooms do not "
            "independently produce that in the time available; this is one distribution event."
        )
    if kind is SharedOriginKind.SAME_PRESS_RELEASE:
        return (
            f"{count} pair(s) reproduce a press release's quotations verbatim. A press "
            "release establishes what its author said, and republishing it establishes only "
            "that it was republished."
        )
    return f"{count} pair(s): {exemplar.shared_material or kind.value}"


def _corroborating_publishers(
    origin_ids: Sequence[str], by_id: Mapping[str, ArticleFingerprint]
) -> set[str]:
    """Which origins constitute an independent observation of the subject matter.

    An origin is not automatically corroboration. Three classes are excluded, and
    each exclusion is a claim about what an artefact can establish, never about
    who produced it:

    * **Opinion and editorial.** They assert a position. A position is not an
      observation, however well argued, and counting it as one would let volume
      of commentary masquerade as weight of evidence.
    * **Press releases.** A party's own account of itself is strong evidence of
      what that party said and no evidence that it is so.
    * **Items declaring themselves non-original.** A piece that says it is
      syndicated, derivative or aggregated has told us it is not an observation.

    What remains must also carry something observational — a quotation, a
    grounded primary source, or retrieved full text — because an original that
    contains nothing checkable corroborates nothing.
    """
    excluded_types = {
        ArticleType.OPINION_COLUMN,
        ArticleType.EDITORIAL,
        ArticleType.PRESS_RELEASE,
    }
    excluded_independence = {
        Independence.SYNDICATED,
        Independence.DERIVATIVE,
        Independence.AGGREGATED,
    }
    publishers: set[str] = set()
    for origin_id in origin_ids:
        fp = by_id[origin_id]
        if fp.article_type in excluded_types:
            continue
        if fp.declared_independence in excluded_independence:
            continue
        if not (fp.quotations or fp.grounding_refs or fp.body_available):
            continue
        publishers.add(fp.publisher_id)
    return publishers


def _analysis_note(
    *,
    total: int,
    distinct: int,
    corroborating: set[str],
    groups: Sequence[OriginGroup],
    basis_note: str,
) -> str:
    """State the finding in the terms a reader needs, not in the terms of a score."""
    if total == 0:
        return "No items supplied: there is nothing to be independent of."
    reproduced = sum(len(g.downstream_ids) for g in groups if g.reproduction)
    parts = [
        f"{total} published item(s) trace back to {distinct} distinct original source(s).",
    ]
    if reproduced:
        parts.append(
            f"{reproduced} item(s) reproduce another item's text rather than observing "
            "independently; republication is not corroboration and these add volume only."
        )
    else:
        parts.append("No reproduction of another item's text was detected between these items.")
    parts.append(
        f"{len(corroborating)} source(s) contribute an independent observation that may "
        "raise confidence downstream."
    )
    if distinct == 1 and total > 1:
        parts.append(
            "Everything here is one observation. Treating this coverage as agreement "
            "between many sources would be a counting error, not a finding."
        )
    parts.append(basis_note + ".")
    return " ".join(parts)


#: Names of every threshold, so a UI can render the settings table without
#: reaching into dataclass internals. Every number this module decides with is
#: reachable from here.
CONFIG_FIELDS: Final[tuple[str, ...]] = tuple(IndependenceConfig.__dataclass_fields__)
