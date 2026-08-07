"""Warm phase 6: grouping coverage into the things it is actually about.

A pile of articles is not evidence about anything until you know which of them
are the same story, which are different stories about the same reform, and which
are separate events that happen to share vocabulary. Phase 6 does that grouping —
and then, immediately and inseparably, attaches to every group the count of how
many distinct originals lie behind it.

The two operations are joined on purpose. Clustering alone is dangerous: it
produces a tidy object labelled "sixty-one articles on the levy" whose size reads,
to any human and to any downstream score, as weight of evidence. It is not.
Sixty-one articles carrying one agency's file is one observation with a large
distribution list. :class:`~aleph.core.models.NewsCluster` therefore *requires*
an ``independence_analysis``, and this module never constructs a cluster without
running :mod:`aleph.news.independence` over its members first. A cluster that
could be published without that number would invite exactly the volume-as-truth
reading Aleph exists to prevent.

Four cluster kinds, each answering a different question:

``story_cluster``
    Items covering one story. The default grouping.
``event``
    A story cluster tight enough in time to be a single occurrence rather than a
    running subject — a vote, a publication, a press conference. Separated
    because "how much was written about the reform" and "how many things
    happened" are different questions with different answers.
``claim_cluster``
    Restatements of one assertion, gathered so that a claim can be evaluated once
    against evidence rather than forty times against forty paraphrases.
``reform_component``
    Coverage routed to the part of the document it concerns, so that silence
    about a provision becomes visible as silence rather than being absorbed into
    a general total.

The clustering itself is TF-IDF cosine similarity with average-linkage
agglomerative merging, written out in plain Python. No scikit-learn, no learned
embedding. That is a deliberate constraint rather than a limitation to apologise
for: this module's output is shown to readers as "these articles are the same
story", and the reason must be inspectable — shared distinctive terms, an
overlapping time window, common entities — rather than a distance in a space
nobody can look at. Every merge decision is reconstructible from
:class:`ClusterDiagnostics`.

Three signals combine into the similarity used for merging: lexical (TF-IDF
cosine over unigrams and bigrams), entity (overlap of topic and grounding
references), and temporal (proximity of publication). Weights are in
:class:`ClusterConfig` and are exposed rather than tuned in secret.

Ids are stable and ordering is deterministic. A cluster is named after its
lexicographically smallest member, not after a run-time counter, so re-analysing
a document next month produces a bundle that can be diffed against this one
instead of looking like a complete rewrite. Nothing here reads a clock or the
network, and nothing here consults a publisher's identity: labels describe
subject matter, never outlets and never their politics.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from aleph.core.enums import (
    ClusterKind,
    ConfidenceEffect,
    ConfidenceFactor,
    UncertaintyKind,
)
from aleph.core.ids import cluster_id as make_cluster_id
from aleph.core.ids import id_parts, stable_hash
from aleph.core.models import (
    Confidence,
    ConfidenceBasis,
    DateRange,
    IndependenceAnalysis,
    NewsArticle,
    NewsCluster,
    Uncertainty,
)
from aleph.news.independence import (
    DEFAULT_CONFIG as DEFAULT_INDEPENDENCE_CONFIG,
)
from aleph.news.independence import (
    IndependenceConfig,
    detailed_analysis,
    normalise_text,
    tokenise,
)

__all__ = [
    "DEFAULT_CLUSTER_CONFIG",
    "ClusterConfig",
    "ClusterDiagnostics",
    "ClusteringResult",
    "ReformComponent",
    "cluster_articles",
    "cluster_claims",
    "cluster_by_reform_component",
    "detect_events",
    "tfidf_vectors",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClusterConfig:
    """Every number the clustering decides with, in one place.

    The weights sum to one by construction (they are normalised at use), and they
    are settings rather than findings. A deployment that believes entity overlap
    matters more than shared vocabulary can say so here and see the effect,
    rather than discovering that the pipeline has an opinion it never declared.
    """

    merge_threshold: float = 0.34
    """Combined similarity at or above which two clusters merge under average
    linkage. Set to favour splitting: two clusters a reader can see are one story
    are a visible, correctable error, whereas two stories silently merged produce
    a cluster whose independence count and date range are both wrong."""

    claim_merge_threshold: float = 0.30
    """Threshold for :func:`cluster_claims`, which is lower than the article one
    rather than higher. A claim is one or two sentences, so its TF-IDF vector is
    sparse and cosine values compress towards zero: two genuine paraphrases score
    around 0.3 where two full articles about the same story score around 0.6.
    Reusing the article threshold here would leave every paraphrase in its own
    cluster and produce forty verdicts for one assertion — the exact failure the
    function exists to prevent. Separation stays wide: an unrelated claim scores
    at or near zero, not just below."""

    lexical_weight: float = 0.6
    entity_weight: float = 0.25
    temporal_weight: float = 0.15

    use_bigrams: bool = True
    """Bigrams distinguish "water levy" from articles that merely mention water
    and mention a levy. Unigrams alone over-merge on shared subject vocabulary."""

    min_term_length: int = 3
    max_document_frequency: float = 0.85
    """Terms appearing in more than this share of items are dropped: a word every
    article uses cannot tell any two of them apart."""

    min_document_frequency: int = 1

    temporal_half_life_hours: float = 72.0
    """Publication-gap at which the temporal signal has decayed to one half.
    Generous, because a running story legitimately spans days."""

    event_window_hours: float = 36.0
    """A story cluster whose members all fall inside this window is treated as
    one event rather than a running subject."""

    min_cluster_size: int = 1
    """Singletons are kept. A story only one outlet covered is a real and
    reportable state of the world — often the most interesting one — and dropping
    it would silently bias the record towards whatever was covered widely."""

    label_terms: int = 4
    """Distinctive terms used to name a cluster."""


DEFAULT_CLUSTER_CONFIG: Final[ClusterConfig] = ClusterConfig()

_TOKEN_STOP_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d{1,2}$")


# ---------------------------------------------------------------------------
# TF-IDF, written out
# ---------------------------------------------------------------------------


def _features(text: str, config: ClusterConfig) -> list[str]:
    """Unigrams and bigrams of normalised text, with useless tokens dropped.

    No stop-word list is used, because a fixed list is language-specific and
    Aleph must work on documents in languages nobody configured it for. Document
    frequency does the same job in a way that adapts to the corpus at hand:
    whatever every article says is, by construction, not distinctive here.
    """
    tokens = [
        t
        for t in tokenise(text)
        if len(t) >= config.min_term_length and not _TOKEN_STOP_PATTERN.match(t)
    ]
    features = list(tokens)
    if config.use_bigrams:
        features.extend(f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False))
    return features


def tfidf_vectors(
    documents: Mapping[str, str], *, config: ClusterConfig = DEFAULT_CLUSTER_CONFIG
) -> dict[str, dict[str, float]]:
    """Build L2-normalised TF-IDF vectors, deterministically.

    Smoothed IDF (``log((1 + N) / (1 + df)) + 1``) so that a term appearing in
    every document still carries a small non-zero weight rather than vanishing
    and taking its document's whole vector with it — which is what an unsmoothed
    formula does to a two-document corpus, and a two-article cluster is a case
    Aleph meets constantly.

    Returns a mapping from document id to a sparse term->weight mapping. Keys are
    inserted in sorted order so serialisation is byte-stable.
    """
    tokenised = {doc_id: _features(text, config) for doc_id, text in sorted(documents.items())}
    total = len(tokenised) or 1

    document_frequency: dict[str, int] = {}
    for features in tokenised.values():
        for term in set(features):
            document_frequency[term] = document_frequency.get(term, 0) + 1

    keep = {
        term
        for term, df in document_frequency.items()
        if df >= config.min_document_frequency
        and (total < 3 or df / total <= config.max_document_frequency)
    }

    vectors: dict[str, dict[str, float]] = {}
    for doc_id, features in tokenised.items():
        counts: dict[str, int] = {}
        for term in features:
            if term in keep:
                counts[term] = counts.get(term, 0) + 1
        if not counts:
            vectors[doc_id] = {}
            continue
        max_count = max(counts.values())
        weights: dict[str, float] = {}
        for term in sorted(counts):
            tf = 0.5 + 0.5 * counts[term] / max_count
            idf = math.log((1 + total) / (1 + document_frequency[term])) + 1.0
            weights[term] = tf * idf
        norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        vectors[doc_id] = {term: w / norm for term, w in weights.items()}
    return vectors


def _cosine(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    """Cosine of two L2-normalised sparse vectors: iterate the shorter one."""
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(weight * right.get(term, 0.0) for term, weight in left.items())


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClusterDiagnostics:
    """Why a cluster has the members it has.

    Kept because a grouping shown to a reader as "these are the same story" is an
    assertion about other people's work, and every such assertion in Aleph must be
    openable. ``cohesion`` is the mean pairwise similarity inside the cluster;
    ``separation`` is the highest similarity to anything outside it. A cluster
    whose separation approaches its cohesion is one a reader should be told is
    borderline, and :func:`_cluster_uncertainties` does tell them.
    """

    cluster_id: str
    member_ids: tuple[str, ...]
    cohesion: float
    separation: float
    top_terms: tuple[tuple[str, float], ...]
    merge_trace: tuple[str, ...]
    """Human-readable record of each merge, in the order performed."""


@dataclass(frozen=True, slots=True)
class ClusteringResult:
    """Clusters plus everything needed to argue with them."""

    clusters: tuple[NewsCluster, ...]
    diagnostics: tuple[ClusterDiagnostics, ...]
    config: ClusterConfig = DEFAULT_CLUSTER_CONFIG
    unassigned_ids: tuple[str, ...] = ()
    """Items no cluster could take. Reported rather than dropped: an article that
    fits nothing is a gap in the clustering, not an absence of coverage."""

    def by_id(self, cluster_id: str) -> NewsCluster | None:
        return next((c for c in self.clusters if c.id == cluster_id), None)

    def diagnostics_for(self, cluster_id: str) -> ClusterDiagnostics | None:
        return next((d for d in self.diagnostics if d.cluster_id == cluster_id), None)


# ---------------------------------------------------------------------------
# Agglomeration
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _WorkingCluster:
    members: list[str]
    trace: list[str] = field(default_factory=list)

    @property
    def anchor(self) -> str:
        return min(self.members)


def _agglomerate(
    ids: Sequence[str],
    similarity: Mapping[tuple[str, str], float],
    *,
    threshold: float,
) -> list[_WorkingCluster]:
    """Average-linkage agglomerative merging with a fully determined order.

    Each round selects the single best merge across all cluster pairs, breaking
    ties on the anchor ids so the outcome cannot depend on dictionary iteration
    order or on the sequence the articles arrived in. That is slower than a
    heap-based scheme and it is the right trade: a clustering that changed when
    the input was shuffled would make every bundle undiffable, and two runs would
    disagree about how many independent sources exist.

    Average rather than single linkage because single linkage chains — one
    borderline article bridges two unrelated stories and the pair becomes one
    cluster with a wrong date range and a wrong independence count.
    """
    clusters = [_WorkingCluster(members=[i]) for i in sorted(ids)]

    def pair_similarity(a: _WorkingCluster, b: _WorkingCluster) -> float:
        total = 0.0
        for left in a.members:
            for right in b.members:
                key = (left, right) if left < right else (right, left)
                total += similarity.get(key, 0.0)
        return total / (len(a.members) * len(b.members))

    while len(clusters) > 1:
        best: tuple[float, str, str, int, int] | None = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                score = pair_similarity(clusters[i], clusters[j])
                if score < threshold:
                    continue
                candidate = (-score, clusters[i].anchor, clusters[j].anchor, i, j)
                if best is None or candidate < best:
                    best = candidate
        if best is None:
            break
        _, _, _, i, j = best
        merged_score = -best[0]
        left, right = clusters[i], clusters[j]
        left.trace.append(
            f"merged {right.anchor} (+{len(right.members)} item(s)) into {left.anchor} "
            f"at average-linkage similarity {merged_score:.3f}"
        )
        left.trace.extend(right.trace)
        left.members = sorted({*left.members, *right.members})
        clusters.pop(j)

    return clusters


# ---------------------------------------------------------------------------
# Article clustering
# ---------------------------------------------------------------------------


def _article_text(article: NewsArticle) -> str:
    """The text a cluster decision is made over.

    Headline, dek, Aleph's neutral summary and the quotations. Deliberately not
    the publisher name or the author: a clustering that could see the outlet
    would learn to group by outlet, and a "story" defined by who wrote it is not
    a story.
    """
    parts = [article.headline]
    if article.dek:
        parts.append(article.dek)
    parts.append(article.neutral_summary)
    parts.extend(q.text for q in article.quotations)
    parts.extend(p.text for p in article.predictions)
    return "\n".join(parts)


def _article_entities(article: NewsArticle) -> frozenset[str]:
    """Structured references that say what an article is about.

    Topic refs, grounded primary sources and claim ids — all of them ids assigned
    by earlier phases, so this signal is independent of wording and survives
    translation and paraphrase, which the lexical signal does not.
    """
    return frozenset(
        {
            *article.cluster_ids,
            *(g.ref for g in article.primary_source_grounding),
            *article.claim_ids,
            *(e.axis.value for e in article.impact_emphasis),
        }
    )


def _instant(article: NewsArticle) -> datetime | None:
    for value in (article.published_at, article.retrieved_at):
        if not value:
            continue
        text = value.strip()
        try:
            if text.endswith("Z"):
                return datetime.fromisoformat(text[:-1]).replace(tzinfo=UTC)
            parsed = datetime.fromisoformat(text)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _temporal_similarity(
    left: datetime | None, right: datetime | None, *, half_life_hours: float
) -> float:
    """Exponential decay in publication gap, or a neutral 0.5 when unknown.

    Unknown returns the midpoint rather than zero on purpose: a missing date is
    an absence of information about timing, not evidence that two items are far
    apart, and scoring it as far apart would let poor metadata split a real story.
    """
    if left is None or right is None:
        return 0.5
    hours = abs((left - right).total_seconds()) / 3600.0
    return math.exp(-math.log(2) * hours / max(half_life_hours, 1e-6))


def cluster_articles(
    articles: Sequence[NewsArticle],
    *,
    kind: ClusterKind = ClusterKind.STORY_CLUSTER,
    bodies: Mapping[str, str] | None = None,
    known_errors: Mapping[str, str] | None = None,
    config: ClusterConfig = DEFAULT_CLUSTER_CONFIG,
    independence_config: IndependenceConfig = DEFAULT_INDEPENDENCE_CONFIG,
    topic_refs: Mapping[str, Sequence[str]] | None = None,
) -> ClusteringResult:
    """Group articles into clusters, each carrying its own independence analysis.

    Args:
        articles: Items to group. Input order does not affect the result.
        kind: Cluster kind to label the output with.
        bodies: Full article text where available, passed through to the
            independence analysis. Its absence is recorded, never worked around.
        known_errors: Known-erroneous strings, for the ``shared_error`` signal.
        config: Clustering thresholds and weights.
        independence_config: Thresholds for the independence signals.
        topic_refs: Extra entity references per article id, from the topic graph.

    Returns:
        A :class:`ClusteringResult`. Clusters are ordered by size descending, then
        by earliest publication, then by id — deterministic, and it puts the
        loudest coverage first *with its independence count attached*, so a reader
        meets the volume and the correction at the same moment.
    """
    if not articles:
        return ClusteringResult(clusters=(), diagnostics=(), config=config)

    by_id = {a.id: a for a in sorted(articles, key=lambda a: a.id)}
    ids = sorted(by_id)

    texts = {aid: _article_text(by_id[aid]) for aid in ids}
    if bodies:
        texts = {aid: f"{texts[aid]}\n{bodies.get(aid, '')}".strip() for aid in ids}
    vectors = tfidf_vectors(texts, config=config)

    entities = {
        aid: _article_entities(by_id[aid]) | frozenset((topic_refs or {}).get(aid, ()))
        for aid in ids
    }
    instants = {aid: _instant(by_id[aid]) for aid in ids}

    weight_total = config.lexical_weight + config.entity_weight + config.temporal_weight or 1.0
    similarity: dict[tuple[str, str], float] = {}
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            lexical = _cosine(vectors[left], vectors[right])
            entity = _jaccard(entities[left], entities[right])
            temporal = _temporal_similarity(
                instants[left], instants[right], half_life_hours=config.temporal_half_life_hours
            )
            combined = (
                config.lexical_weight * lexical
                + config.entity_weight * entity
                + config.temporal_weight * temporal
            ) / weight_total
            similarity[(left, right)] = combined

    working = _agglomerate(ids, similarity, threshold=config.merge_threshold)

    clusters: list[NewsCluster] = []
    diagnostics: list[ClusterDiagnostics] = []
    for group in working:
        if len(group.members) < config.min_cluster_size:
            continue
        members = tuple(sorted(group.members))
        cid = _stable_cluster_id(members, kind)
        members_articles = [by_id[m] for m in members]
        report = detailed_analysis(
            members_articles,
            bodies=bodies,
            known_errors=known_errors,
            config=independence_config,
        )
        top_terms = _top_terms(members, vectors, config.label_terms)
        cohesion = _cohesion(members, similarity)
        separation = _separation(members, ids, similarity)

        clusters.append(
            NewsCluster(
                id=cid,
                kind=kind,
                label=_label(top_terms, members_articles),
                summary=_summary(members_articles, report.analysis),
                article_ids=list(members),
                claim_ids=sorted({c for a in members_articles for c in a.claim_ids}),
                date_range=_date_range(members_articles),
                independence_analysis=report.analysis,
                topic_refs=sorted(
                    {ref for aid in members for ref in (topic_refs or {}).get(aid, ())}
                ),
                confidence=_cluster_confidence(report.analysis, cohesion, separation, members),
                uncertainties=_cluster_uncertainties(
                    report.analysis, cohesion, separation, report.text_basis_note
                ),
            )
        )
        diagnostics.append(
            ClusterDiagnostics(
                cluster_id=cid,
                member_ids=members,
                cohesion=round(cohesion, 4),
                separation=round(separation, 4),
                top_terms=top_terms,
                merge_trace=tuple(group.trace),
            )
        )

    order = _ordering(clusters)
    return ClusteringResult(
        clusters=tuple(clusters[i] for i in order),
        diagnostics=tuple(diagnostics[i] for i in order),
        config=config,
    )


def _ordering(clusters: Sequence[NewsCluster]) -> list[int]:
    """Indices sorted by size descending, then earliest date, then id."""
    return sorted(
        range(len(clusters)),
        key=lambda i: (
            -len(clusters[i].article_ids),
            clusters[i].date_range.start,
            clusters[i].id,
        ),
    )


def _stable_cluster_id(members: Sequence[str], kind: ClusterKind) -> str:
    """Name a cluster after its lexicographically smallest member.

    Stability is the requirement, and it rules out the two obvious choices. A
    run-time counter renumbers everything whenever one article is added. A hash of
    the membership changes identity whenever membership changes, which is
    precisely when a reader most wants to see that the cluster is the same
    cluster with one more item in it. The smallest member id changes only if that
    member leaves, and it is readable: ``cluster:story_cluster:diario-a.1`` says
    what it is without a lookup.
    """
    anchor = min(members) if members else "empty"
    try:
        tail = ".".join(id_parts(anchor))
    except ValueError:
        tail = stable_hash(anchor, length=10)
    return make_cluster_id(tail, kind=kind.value)


def _top_terms(
    members: Sequence[str], vectors: Mapping[str, Mapping[str, float]], count: int
) -> tuple[tuple[str, float], ...]:
    """The terms that most distinguish this cluster, by summed TF-IDF weight."""
    totals: dict[str, float] = {}
    for member in members:
        for term, weight in vectors.get(member, {}).items():
            totals[term] = totals.get(term, 0.0) + weight
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return tuple((term.replace("_", " "), round(weight, 4)) for term, weight in ranked[:count])


def _label(top_terms: Sequence[tuple[str, float]], articles: Sequence[NewsArticle]) -> str:
    """Name a cluster by its subject matter and nothing else.

    Built from distinctive terms rather than from a headline, because a headline
    is one outlet's framing and adopting it would make Aleph's own label carry
    that framing. Falls back to a shared headline prefix only when the vocabulary
    is too uniform to distinguish anything.
    """
    if top_terms:
        return ", ".join(term for term, _ in top_terms)
    if articles:
        return normalise_text(articles[0].headline)[:80] or "unlabelled coverage"
    return "unlabelled coverage"


def _summary(articles: Sequence[NewsArticle], analysis: IndependenceAnalysis) -> str:
    """One sentence a reader can act on, with the correction attached to the count."""
    publishers = len({a.publisher.id for a in articles})
    return (
        f"{len(articles)} published item(s) from {publishers} publisher(s), tracing back to "
        f"{analysis.distinct_original_sources} distinct original source(s); "
        f"{analysis.independent_corroboration_count} of those contribute independent "
        "corroboration. Item count measures distribution, not evidence."
    )


def _date_range(articles: Sequence[NewsArticle]) -> DateRange:
    """Earliest and latest publication date in the cluster.

    Falls back to the retrieval date for items that state no publication date,
    since when Aleph saw an item is at least a real observation. Only when both
    are missing or unparseable does the epoch stand in — a value obviously wrong
    rather than plausibly wrong, so a reader notices the missing metadata instead
    of trusting a fabricated date.
    """
    dates = sorted(
        {(_instant(a) or datetime(1970, 1, 1, tzinfo=UTC)).date().isoformat() for a in articles}
    )
    return DateRange(start=dates[0], end=dates[-1])


def _cohesion(members: Sequence[str], similarity: Mapping[tuple[str, str], float]) -> float:
    """Mean pairwise similarity inside the cluster. 1.0 for a singleton."""
    if len(members) < 2:
        return 1.0
    scores = [
        similarity.get((a, b) if a < b else (b, a), 0.0)
        for i, a in enumerate(members)
        for b in members[i + 1 :]
    ]
    return sum(scores) / len(scores) if scores else 0.0


def _separation(
    members: Sequence[str], all_ids: Sequence[str], similarity: Mapping[tuple[str, str], float]
) -> float:
    """Highest similarity between a member and a non-member. 0.0 when alone."""
    member_set = set(members)
    outside = [i for i in all_ids if i not in member_set]
    if not outside:
        return 0.0
    return max(
        (similarity.get((a, b) if a < b else (b, a), 0.0) for a in members for b in outside),
        default=0.0,
    )


def _cluster_confidence(
    analysis: IndependenceAnalysis,
    cohesion: float,
    separation: float,
    members: Sequence[str],
) -> Confidence:
    """Confidence that this cluster is one story, backed by independent observation.

    Two things are being asserted and both must be paid for. Cohesion minus
    separation says how confident Aleph is that these items belong together and
    that nothing outside belongs with them. The independence ratio says how much
    of the group is actual observation rather than redistribution — and it is a
    *cap*, not an addend: a beautifully cohesive cluster of forty copies of one
    file is a well-identified single observation, and no amount of tightness may
    let it read as strongly evidenced.
    """
    margin = max(0.0, cohesion - separation)
    structural = min(1.0, 0.4 + 0.6 * margin)
    independent = analysis.independent_corroboration_count
    independence_cap = min(1.0, 0.35 + 0.2 * independent) if len(members) > 1 else 0.6
    value = round(min(structural, independence_cap), 3)

    basis = [
        ConfidenceBasis(
            factor=ConfidenceFactor.EVIDENCE_AGREEMENT,
            effect=ConfidenceEffect.RAISES if margin > 0.15 else ConfidenceEffect.LOWERS,
            note=(
                f"internal cohesion {cohesion:.2f} against nearest outside similarity "
                f"{separation:.2f}"
            ),
        ),
        ConfidenceBasis(
            factor=ConfidenceFactor.SOURCE_INDEPENDENCE,
            effect=ConfidenceEffect.RAISES if independent > 1 else ConfidenceEffect.LOWERS,
            note=(
                f"{analysis.total_articles} item(s) collapse to "
                f"{analysis.distinct_original_sources} original source(s), of which "
                f"{independent} contribute independent corroboration"
            ),
        ),
    ]
    limiting = (
        "only one independent original lies behind this coverage; the item count is "
        "distribution, not corroboration"
        if independent <= 1 and analysis.total_articles > 1
        else (
            "cluster boundary is close to neighbouring coverage"
            if margin <= 0.15 and len(members) > 1
            else None
        )
    )
    return Confidence(evidence_confidence=value, basis=basis, limiting_factor=limiting)


def _cluster_uncertainties(
    analysis: IndependenceAnalysis, cohesion: float, separation: float, basis_note: str
) -> list[Uncertainty]:
    """State what remains unresolved about this cluster, rather than rounding it away."""
    out: list[Uncertainty] = []
    if analysis.total_articles > 1 and analysis.distinct_original_sources == 1:
        out.append(
            Uncertainty(
                statement=(
                    f"All {analysis.total_articles} items trace to a single original. Nothing "
                    "here is corroborated by a second observation."
                ),
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by=(
                    "an item from a source that observed the subject directly rather than "
                    "reproducing this one"
                ),
            )
        )
    if separation >= cohesion - 0.05 and analysis.total_articles > 1:
        out.append(
            Uncertainty(
                statement=(
                    "This cluster's boundary is weak: at least one item outside it is about "
                    "as similar to its members as they are to each other."
                ),
                kind=UncertaintyKind.DEFINITIONAL_AMBIGUITY,
                resolvable_by="entity references from the topic graph, or full article text",
            )
        )
    if "full text for 0 of" in basis_note:
        out.append(
            Uncertainty(
                statement=(
                    "Independence was assessed without full article text; the syndication "
                    "finding rests on headlines, summaries and quotations alone."
                ),
                kind=UncertaintyKind.MISSING_EVIDENCE,
                resolvable_by="retrieval of the article bodies",
            )
        )
    return out


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def detect_events(
    result: ClusteringResult,
    articles: Sequence[NewsArticle],
    *,
    config: ClusterConfig = DEFAULT_CLUSTER_CONFIG,
) -> tuple[NewsCluster, ...]:
    """Re-label the story clusters that describe a single occurrence.

    A story cluster spanning three weeks is a running subject; one whose members
    all fall inside ``event_window_hours`` is a thing that happened — a vote, a
    publication, a press conference. The distinction matters because "how many
    events occurred" and "how much was written" are different questions, and a
    timeline built from the second is a chart of press attention presented as a
    chart of events.

    Returns new clusters with ``kind = event`` and their own ids; the story
    clusters they derive from are left untouched.
    """
    by_id = {a.id: a for a in articles}
    events: list[NewsCluster] = []
    for cluster in result.clusters:
        if cluster.kind is not ClusterKind.STORY_CLUSTER or len(cluster.article_ids) < 2:
            continue
        instants = [_instant(by_id[aid]) for aid in cluster.article_ids if aid in by_id]
        known = [i for i in instants if i is not None]
        if len(known) < 2:
            continue
        span_hours = (max(known) - min(known)).total_seconds() / 3600.0
        if span_hours > config.event_window_hours:
            continue
        members = tuple(cluster.article_ids)
        events.append(
            cluster.model_copy(
                update={
                    "id": _stable_cluster_id(members, ClusterKind.EVENT),
                    "kind": ClusterKind.EVENT,
                    "summary": (
                        f"{cluster.summary} All items fall within {span_hours:.1f}h, which is "
                        "one occurrence rather than a running subject."
                    ),
                }
            )
        )
    return tuple(sorted(events, key=lambda c: (c.date_range.start, c.id)))


# ---------------------------------------------------------------------------
# Claim clusters
# ---------------------------------------------------------------------------


def cluster_claims(
    claims: Mapping[str, str],
    *,
    article_ids_by_claim: Mapping[str, Sequence[str]] | None = None,
    articles: Sequence[NewsArticle] = (),
    bodies: Mapping[str, str] | None = None,
    config: ClusterConfig = DEFAULT_CLUSTER_CONFIG,
    independence_config: IndependenceConfig = DEFAULT_INDEPENDENCE_CONFIG,
) -> ClusteringResult:
    """Group restatements of one assertion into a single claim cluster.

    The point is to evaluate a claim once. Forty paraphrases of "the levy will
    raise X" evaluated separately produce forty verdicts, forty confidence
    figures and the appearance of forty independent findings — when there is one
    claim, one evidence base and one answer.

    Each resulting cluster still carries an independence analysis over whichever
    articles carried its member claims, because how many outlets restated a claim
    is exactly the number a reader is most likely to misread as agreement.

    Args:
        claims: Claim id to claim text.
        article_ids_by_claim: Which articles carried each claim.
        articles: The article objects, for the independence analysis.
        bodies: Full text where available.
    """
    if not claims:
        return ClusteringResult(clusters=(), diagnostics=(), config=config)

    ids = sorted(claims)
    vectors = tfidf_vectors({cid: claims[cid] for cid in ids}, config=config)
    similarity: dict[tuple[str, str], float] = {}
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            similarity[(left, right)] = _cosine(vectors[left], vectors[right])

    # Claim text is short, so the lexical signal is the whole signal and cosine
    # values compress; see ClusterConfig.claim_merge_threshold for why that means
    # a lower threshold rather than a higher one.
    working = _agglomerate(ids, similarity, threshold=config.claim_merge_threshold)

    articles_by_id = {a.id: a for a in articles}
    clusters: list[NewsCluster] = []
    diagnostics: list[ClusterDiagnostics] = []
    for group in working:
        members = tuple(sorted(group.members))
        cid = _stable_cluster_id(members, ClusterKind.CLAIM_CLUSTER)
        carrying_ids = sorted(
            {
                aid
                for claim in members
                for aid in (article_ids_by_claim or {}).get(claim, ())
                if aid in articles_by_id
            }
        )
        carrying = [articles_by_id[aid] for aid in carrying_ids]
        report = detailed_analysis(carrying, bodies=bodies, config=independence_config)
        top_terms = _top_terms(members, vectors, config.label_terms)
        cohesion = _cohesion(members, similarity)
        separation = _separation(members, ids, similarity)

        clusters.append(
            NewsCluster(
                id=cid,
                kind=ClusterKind.CLAIM_CLUSTER,
                label=_label(top_terms, carrying),
                summary=(
                    f"{len(members)} restatement(s) of one assertion, carried by "
                    f"{len(carrying)} item(s) from "
                    f"{report.analysis.distinct_original_sources} distinct original source(s). "
                    "Restatement is not corroboration: this is one claim to evaluate once."
                ),
                article_ids=carrying_ids,
                claim_ids=list(members),
                date_range=(
                    _date_range(carrying)
                    if carrying
                    else DateRange(start="1970-01-01", end="1970-01-01")
                ),
                independence_analysis=report.analysis,
                confidence=_cluster_confidence(report.analysis, cohesion, separation, members),
                uncertainties=_cluster_uncertainties(
                    report.analysis, cohesion, separation, report.text_basis_note
                ),
            )
        )
        diagnostics.append(
            ClusterDiagnostics(
                cluster_id=cid,
                member_ids=members,
                cohesion=round(cohesion, 4),
                separation=round(separation, 4),
                top_terms=top_terms,
                merge_trace=tuple(group.trace),
            )
        )

    order = _ordering(clusters)
    return ClusteringResult(
        clusters=tuple(clusters[i] for i in order),
        diagnostics=tuple(diagnostics[i] for i in order),
        config=config,
    )


# ---------------------------------------------------------------------------
# Reform-component clusters
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReformComponent:
    """One part of a document that coverage can be routed to.

    Supplied by the earlier phases — a provision, a section, a topic-graph
    subgraph — because deciding what a reform's components *are* is a reading of
    the document, and this module reads coverage, not documents.
    """

    key: str
    """Stable identifier fragment, used to build the cluster id."""
    label: str
    descriptor: str
    """Text describing the component: its title, its operative sentence, its
    defined terms. Coverage is matched against this."""
    refs: tuple[str, ...] = ()
    """Provision, proposition or node ids belonging to this component."""


def cluster_by_reform_component(
    articles: Sequence[NewsArticle],
    components: Sequence[ReformComponent],
    *,
    bodies: Mapping[str, str] | None = None,
    known_errors: Mapping[str, str] | None = None,
    config: ClusterConfig = DEFAULT_CLUSTER_CONFIG,
    independence_config: IndependenceConfig = DEFAULT_INDEPENDENCE_CONFIG,
    min_similarity: float = 0.06,
    single_assignment: bool = False,
) -> ClusteringResult:
    """Route coverage to the parts of a document it concerns.

    Unlike the other functions here this is not a partition: by default an
    article joins *every* component it scores above ``min_similarity`` on.
    Coverage is not exclusive — one article routinely reports a rate, its
    exemptions and its start date — and forcing a single best match would record
    the two components it also covered as uncovered. Since the entire purpose of
    this function is to make uncovered components visible, an assignment rule
    that manufactures false silence would defeat it. Pass
    ``single_assignment=True`` for a strict partition where that is wanted.

    Articles matching no component are returned in ``unassigned_ids`` rather than
    forced somewhere.

    Components with no coverage still produce a cluster, with zero members. That
    is the other half of the point. A provision nobody wrote about is among the
    most informative things a coverage analysis can report — asymmetric attention
    is invisible when only the covered parts appear — and it can only be reported
    if the uncovered component is present in the output. Its ``uncertainties``
    say plainly that genuine silence and a retrieval gap are different things and
    that this function cannot tell them apart.

    Note the deliberate continuity with :func:`cluster_articles`: a component
    cluster's independence analysis still collapses syndication among its
    members, so a provision with forty articles and one original reads as thinly
    covered, which is what it is.
    """
    if not components:
        return ClusteringResult(clusters=(), diagnostics=(), config=config)

    by_id = {a.id: a for a in sorted(articles, key=lambda a: a.id)}
    article_ids = sorted(by_id)

    corpus: dict[str, str] = {f"component:{c.key}": c.descriptor for c in components}
    for aid in article_ids:
        text = _article_text(by_id[aid])
        if bodies and bodies.get(aid):
            text = f"{text}\n{bodies[aid]}"
        corpus[aid] = text
    vectors = tfidf_vectors(corpus, config=config)

    assignments: dict[str, list[str]] = {c.key: [] for c in components}
    unassigned: list[str] = []
    for aid in article_ids:
        scored = sorted(
            ((_cosine(vectors[aid], vectors[f"component:{c.key}"]), c.key) for c in components),
            key=lambda item: (-item[0], item[1]),
        )
        # Reference overlap is decisive when present: an article that grounds
        # itself in a provision belongs to that provision's component whatever
        # its vocabulary happens to be. A structured reference from an earlier
        # phase is a stronger statement about aboutness than any word count.
        entity_hits = sorted(
            c.key for c in components if set(c.refs) & _article_entities(by_id[aid])
        )
        if entity_hits:
            targets = entity_hits[:1] if single_assignment else entity_hits
        else:
            above = [key for score, key in scored if score >= min_similarity]
            targets = above[:1] if single_assignment else above
        if not targets:
            unassigned.append(aid)
            continue
        for key in targets:
            assignments[key].append(aid)

    clusters: list[NewsCluster] = []
    diagnostics: list[ClusterDiagnostics] = []
    for component in sorted(components, key=lambda c: c.key):
        members = tuple(sorted(assignments[component.key]))
        member_articles = [by_id[m] for m in members]
        report = detailed_analysis(
            member_articles,
            bodies=bodies,
            known_errors=known_errors,
            config=independence_config,
        )
        cid = make_cluster_id(component.key, kind=ClusterKind.REFORM_COMPONENT.value)
        clusters.append(
            NewsCluster(
                id=cid,
                kind=ClusterKind.REFORM_COMPONENT,
                label=component.label,
                summary=(
                    _summary(member_articles, report.analysis)
                    if members
                    else (
                        "No coverage was found for this component. An uncovered provision is "
                        "a finding about attention, not an absence of substance."
                    )
                ),
                article_ids=list(members),
                claim_ids=sorted({c for a in member_articles for c in a.claim_ids}),
                date_range=(
                    _date_range(member_articles)
                    if members
                    else DateRange(start="1970-01-01", end="1970-01-01")
                ),
                independence_analysis=report.analysis,
                topic_refs=list(component.refs),
                confidence=_cluster_confidence(report.analysis, 1.0, 0.0, members),
                uncertainties=(
                    _cluster_uncertainties(report.analysis, 1.0, 0.0, report.text_basis_note)
                    if members
                    else [
                        Uncertainty(
                            statement=(
                                f"No retrieved item was about {component.label}. This may be "
                                "genuine silence in the coverage or a gap in retrieval, and "
                                "these are different things."
                            ),
                            kind=UncertaintyKind.MISSING_EVIDENCE,
                            resolvable_by=(
                                "targeted queries built from this component's own vocabulary"
                            ),
                        )
                    ]
                ),
            )
        )
        diagnostics.append(
            ClusterDiagnostics(
                cluster_id=cid,
                member_ids=members,
                cohesion=1.0,
                separation=0.0,
                top_terms=_top_terms(members, vectors, config.label_terms),
                merge_trace=(
                    f"routed by best match against component descriptor {component.key!r}",
                ),
            )
        )

    order = sorted(
        range(len(clusters)),
        key=lambda i: (-len(clusters[i].article_ids), clusters[i].id),
    )
    return ClusteringResult(
        clusters=tuple(clusters[i] for i in order),
        diagnostics=tuple(diagnostics[i] for i in order),
        config=config,
        unassigned_ids=tuple(unassigned),
    )
