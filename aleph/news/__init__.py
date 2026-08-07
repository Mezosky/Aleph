"""Where Aleph looks, and how it counts what it finds there.

Three modules, covering warm phases 5 and 6, joined by a single idea: **what was
published and what was observed are different quantities, and only the second is
evidence.**

:mod:`aleph.news.registry`
    The list of sources Aleph may retrieve from. It records what a source *is* —
    what sort of body publishes it, where, in what language, producing what class
    of artefact — and deliberately records nothing about merit. There is no
    credibility, bias, leaning or prestige field, and the loader rejects a file
    carrying one rather than ignoring it. Jurisdiction is a parameter throughout:
    adding a country is adding a block to ``sources.yaml``, never a change to
    Python.

:mod:`aleph.news.independence`
    The count that matters. Near-duplicate detection, shared-quotation analysis,
    wire-attribution parsing, publication-time cascades and shared-citation
    overlap, all implemented on the standard library so that every finding is
    explainable as "these two texts share this passage" rather than as a distance
    in an unlookable space. Its output says how many genuinely distinct originals
    lie behind N published items, with the syndication chains as evidence.

:mod:`aleph.news.cluster`
    Warm phase 6. Groups coverage into story, event, claim and reform-component
    clusters using TF-IDF cosine similarity and average-linkage agglomeration
    written out in plain Python, with entity and time-window signals. Every
    cluster it builds carries an independence analysis, because a cluster's size
    is the number a reader is most likely to mistake for weight of evidence.

The rule these three enforce between them is short: **repeated publication is not
independent corroboration.** Forty outlets carrying one agency's file are one
observation with a large distribution list. A pipeline that counts copies
manufactures confidence out of press-release logistics, and no amount of care
further downstream can undo it — by the time a verdict is written, the inflated
count already looks like agreement between many sources.

Nothing in this package touches the network. Retrieval is gated by the retrieval
policy and reached only through an explicit, deliberate call.
"""

from __future__ import annotations

from aleph.news.cluster import (
    ClusterConfig,
    ClusteringResult,
    ReformComponent,
    cluster_articles,
    cluster_by_reform_component,
    cluster_claims,
    detect_events,
)
from aleph.news.independence import (
    ArticleFingerprint,
    IndependenceConfig,
    IndependenceReport,
    PairEvidence,
    analyse_independence,
    detailed_analysis,
    explain_pair,
    fingerprint_article,
)
from aleph.news.registry import (
    PACKAGED_REGISTRY_PATH,
    RegistryValidationReport,
    SourceFilter,
    SourceRegistryStore,
    UnresolvedSource,
    default_registry,
    filter_sources,
    get_source,
    load_registry,
    validate_registry,
)

__all__ = [
    "PACKAGED_REGISTRY_PATH",
    "ArticleFingerprint",
    "ClusterConfig",
    "ClusteringResult",
    "IndependenceConfig",
    "IndependenceReport",
    "PairEvidence",
    "ReformComponent",
    "RegistryValidationReport",
    "SourceFilter",
    "SourceRegistryStore",
    "UnresolvedSource",
    "analyse_independence",
    "cluster_articles",
    "cluster_by_reform_component",
    "cluster_claims",
    "default_registry",
    "detailed_analysis",
    "detect_events",
    "explain_pair",
    "filter_sources",
    "fingerprint_article",
    "get_source",
    "load_registry",
    "validate_registry",
]
