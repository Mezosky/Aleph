"""Provider-agnostic retrieval, and the politeness that has to come with it.

Phase 4 decides what to look for; this module is how Aleph looks. It is
deliberately an interface with three implementations rather than a crawler,
because the pipeline must be able to run — completely, reproducibly, and with
identical output — when there is no network at all. That is not a convenience for
tests. A system whose analysis silently narrows when a fetch fails will publish
the resulting hole as an absence of coverage, and "we found nothing" is one of the
most consequential things Aleph can say.

So the default provider is :class:`DeterministicMockProvider`, which is offline
and reproducible, and the real one, :class:`RegistryFeedProvider`, reads declared
RSS/Atom/sitemap feeds from the source registry rather than scraping pages.

**Retrieval is off unless someone asks for it.** Aleph's default retrieval mode
is ``manual``: no module may reach the network as a side effect of running the
pipeline. Every method that could emit a request takes ``allow_network`` as a
keyword-only argument defaulting to ``False``, and raises
:class:`~aleph.core.errors.RetrievalDisabledError` rather than fetching. Cached
responses are still served, so a re-run costs a source nothing. Two things follow
that are worth being explicit about: a run is reproducible against a fixed
evidence set, and no server receives traffic that nobody asked for.

**Politeness is structural, not aspirational.** ``robots.txt`` is consulted and
obeyed, and an unchecked host is treated as not-yet-permitted rather than as
permitted. Requests to one host are spaced by a per-host rate limiter. Every
request carries ``ETag``/``If-Modified-Since`` from the on-disk cache, so an
unchanged feed costs a source a 304 and nothing more. The User-Agent identifies
Aleph honestly and points at the project, because anonymous crawling of
public-interest sources is not acceptable behaviour. A hard paywall is a coverage
gap to be reported, never a barrier to be worked around.

Nothing here ranks a source by prestige, and :class:`SearchResult` has no
credibility field. ``tier`` says what kind of artefact an item is, and therefore
what it can establish — a constraint on interpretation, never a shortcut for it.
"""

from __future__ import annotations

import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from aleph.core.config import Config, get_config
from aleph.core.enums import EvidenceTier, Independence, RetrievalMode, SourceKind
from aleph.core.errors import RetrievalDisabledError, RetrievalError
from aleph.core.ids import stable_hash
from aleph.core.models import (
    Feed,
    GeneratedQuery,
    SourceRef,
    SourceRegistryEntry,
)

__all__ = [
    "SEARCH_INTERFACE_VERSION",
    "SearchQuery",
    "SearchResult",
    "SearchProvider",
    "NullSearchProvider",
    "DeterministicMockProvider",
    "RegistryFeedProvider",
    "RateLimiter",
    "RobotsGate",
    "CachedResponse",
    "HttpCache",
    "PoliteFetcher",
    "parse_feed",
    "get_search_provider",
]

SEARCH_INTERFACE_VERSION: Final[str] = "1.0.0"

_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[^\W_]+", re.UNICODE)
_TAG_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
_QUOTED_RE: Final[re.Pattern[str]] = re.compile(r'"([^"]{2,})"')

#: Feeds are XML and XML parsers are a well-known denial-of-service surface.
#: A declared doctype or entity is refused outright rather than parsed: no
#: legitimate syndication feed needs one, and an internal entity definition is
#: the whole of the "billion laughs" attack.
_XML_DOCTYPE_RE: Final[re.Pattern[str]] = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)

_MAX_FEED_BYTES: Final[int] = 8 * 1024 * 1024


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _tokens(text: str) -> list[str]:
    return [_fold(t) for t in _TOKEN_RE.findall(text)]


def _strip_markup(text: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def _utc(value: datetime) -> str:
    """Render a datetime as the contract's UTC timestamp form."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_datetime(raw: str | None) -> str | None:
    """Parse a feed date into a UTC timestamp, or give up cleanly.

    Feeds disagree about date formats, and a wrong date is worse than none: the
    temporal-consistency check downstream would compare a claim against a period
    it was never made in.
    """
    if not raw:
        return None
    text = raw.strip()
    try:
        return _utc(parsedate_to_datetime(text))
    except (TypeError, ValueError, IndexError):
        pass
    candidate = text.replace("Z", "+00:00")
    try:
        return _utc(datetime.fromisoformat(candidate))
    except ValueError:
        pass
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return f"{match.group(0)}T00:00:00Z"
    return None


def _as_bound(value: str | date | datetime | None, *, end_of_day: bool) -> str | None:
    """Normalise a date bound to a comparable UTC timestamp string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, date):
        return f"{value.isoformat()}T{'23:59:59' if end_of_day else '00:00:00'}Z"
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f"{text}T{'23:59:59' if end_of_day else '00:00:00'}Z"
    return _parse_datetime(text)


# ---------------------------------------------------------------------------
# Query and result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """A retrieval request, however it was expressed.

    Accepting either a bare string or a phase-4
    :class:`~aleph.core.models.GeneratedQuery` is what lets the vocabulary's
    routing survive into retrieval: a query the planner aimed at a statistics
    agency arrives here still knowing that, instead of being flattened into a
    string and sent everywhere.
    """

    text: str
    language: str | None = None
    source_ids: tuple[str, ...] = ()
    date_from: str | None = None
    date_to: str | None = None
    expected_tier: EvidenceTier | None = None

    @classmethod
    def coerce(cls, query: str | GeneratedQuery | SearchQuery) -> SearchQuery:
        if isinstance(query, SearchQuery):
            return query
        if isinstance(query, GeneratedQuery):
            return cls(
                text=query.query_text,
                language=query.language,
                source_ids=tuple(query.target_source_ids),
                date_from=query.date_from,
                date_to=query.date_to,
                expected_tier=query.expected_evidence_tier,
            )
        return cls(text=str(query))

    @property
    def phrases(self) -> list[str]:
        """Quoted spans, which must appear verbatim for a phrase match."""
        return [m.group(1) for m in _QUOTED_RE.finditer(self.text)]

    @property
    def terms(self) -> list[str]:
        return _tokens(_QUOTED_RE.sub(" ", self.text)) + [
            token for phrase in self.phrases for token in _tokens(phrase)
        ]


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One item a provider returned, before anything has been read from it.

    A candidate, not evidence. It becomes evidence only once phase 5 has read it,
    written down what it establishes and what it cannot, and attached a quotable
    span — which is why there is no ``statement`` field here and no place to put
    one.

    There is deliberately no credibility, prestige or ranking-by-publisher field.
    ``tier`` records what kind of artefact this is and therefore what it is
    capable of establishing; ``score`` is retrieval relevance and says nothing
    about whether the item is right.
    """

    url: str
    title: str
    snippet: str = ""
    published_at: str | None = None
    publisher: str | None = None
    language: str | None = None
    tier: EvidenceTier = EvidenceTier.JOURNALISM
    independence: Independence = Independence.UNKNOWN
    source_entry_id: str | None = None
    """Registry id of the source this came from, when it came from one."""
    provider: str = "unknown"
    retrieved_at: str | None = None
    score: float = 0.0
    """Retrieval relevance in [0,1]. Not a judgement about the item's content."""
    is_fixture: bool = False
    """True for synthetic results. Consumers MUST surface this: a fixture
    describes no real publication by any real outlet."""
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_source_ref(self, identifier: str) -> SourceRef:
        """Render as the :class:`~aleph.core.models.SourceRef` phase 5 stores."""
        return SourceRef(
            id=identifier,
            title=self.title,
            url=self.url,
            publisher=self.publisher,
            published_at=self.published_at,
            tier=self.tier,
            independence=self.independence,
            language=self.language,
        )


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class SearchProvider(ABC):
    """What every retrieval backend must offer, and what none of them may assume.

    ``allow_network`` is keyword-only and defaults to ``False`` on purpose. Code
    that forgets to pass it fails loudly at the call site rather than quietly
    emitting traffic to a stranger's server, and a run's reproducibility is
    preserved because nothing can change underneath it mid-analysis. An
    implementation that ignores the flag is a defect, not an optimisation.
    """

    name: str = "search-provider"

    @abstractmethod
    def search(
        self,
        query: str | GeneratedQuery | SearchQuery,
        *,
        limit: int = 10,
        since: str | date | datetime | None = None,
        until: str | date | datetime | None = None,
        language: str | None = None,
        allow_network: bool = False,
    ) -> list[SearchResult]:
        """Return candidate items for ``query``, best match first.

        Args:
            query: A string, or a phase-4 :class:`GeneratedQuery` whose routing
                and date bounds are honoured.
            limit: Maximum results.
            since: Lower publication bound. A date string, ``date`` or ``datetime``.
            until: Upper publication bound.
            language: BCP-47 filter. Matching is on the primary subtag, so
                ``es`` matches ``es-CL``.
            allow_network: Must be ``True`` for any outbound request. Providers
                that cannot serve the query from cache or fixtures raise
                :class:`~aleph.core.errors.RetrievalDisabledError` instead.

        Returns:
            Results sorted by descending score, ties broken by url so the order
            is stable between runs.
        """

    def _finalise(
        self,
        results: Iterable[SearchResult],
        *,
        limit: int,
        since: str | date | datetime | None,
        until: str | date | datetime | None,
        language: str | None,
    ) -> list[SearchResult]:
        """Apply the filters and ordering every provider owes its caller.

        Implemented once here so that "limit" and "since" mean the same thing
        whichever backend answered — otherwise a comparison between providers
        would be measuring their filtering conventions rather than their coverage.
        """
        lower = _as_bound(since, end_of_day=False)
        upper = _as_bound(until, end_of_day=True)
        primary = language.split("-")[0].lower() if language else None

        kept: list[SearchResult] = []
        for result in results:
            if lower and result.published_at and result.published_at < lower:
                continue
            if upper and result.published_at and result.published_at > upper:
                continue
            if primary and result.language:
                if result.language.split("-")[0].lower() != primary:
                    continue
            kept.append(result)
        kept.sort(key=lambda r: (-r.score, r.url))
        return kept[: max(0, limit)]


class NullSearchProvider(SearchProvider):
    """Returns nothing, always, and says so.

    The honest configuration for a deployment that has deliberately turned
    retrieval off. Distinct from a provider that errors: an empty result set with
    a named provider lets readiness report "retrieval not configured" rather than
    "nothing was published about this", which are very different findings.
    """

    name = "none"

    def search(
        self,
        query: str | GeneratedQuery | SearchQuery,
        *,
        limit: int = 10,
        since: str | date | datetime | None = None,
        until: str | date | datetime | None = None,
        language: str | None = None,
        allow_network: bool = False,
    ) -> list[SearchResult]:
        return []


# ---------------------------------------------------------------------------
# Deterministic mock
# ---------------------------------------------------------------------------

#: Fictional publishers for synthesised results. Chosen to be obviously
#: non-existent — with a reserved ``.invalid`` host — because a fixture that
#: looked like a real outlet could be mistaken for a real publication, and Aleph
#: must never put words in a real organisation's mouth.
_FIXTURE_PUBLISHERS: Final[tuple[tuple[str, EvidenceTier, Independence], ...]] = (
    ("Fixture Official Register", EvidenceTier.PRIMARY_DOCUMENT, Independence.ORIGINAL_REPORTING),
    (
        "Fixture Legislative Record",
        EvidenceTier.LEGISLATIVE_RECORD,
        Independence.ORIGINAL_REPORTING,
    ),
    (
        "Fixture Technical Review",
        EvidenceTier.OFFICIAL_TECHNICAL_REPORT,
        Independence.ORIGINAL_REPORTING,
    ),
    (
        "Fixture Statistical Office",
        EvidenceTier.STATISTICAL_DATASET,
        Independence.ORIGINAL_REPORTING,
    ),
    ("Fixture Research Quarterly", EvidenceTier.PEER_REVIEWED, Independence.ORIGINAL_REPORTING),
    ("Fixture Daily Report", EvidenceTier.JOURNALISM, Independence.ORIGINAL_REPORTING),
    ("Fixture Wire Service", EvidenceTier.JOURNALISM, Independence.SYNDICATED),
    ("Fixture Policy Digest", EvidenceTier.EXPERT_ANALYSIS, Independence.DERIVATIVE),
)


class DeterministicMockProvider(SearchProvider):
    """Fixture results, identical on every run and on every machine.

    Two jobs. It makes the whole pipeline runnable offline, which is what lets
    the deterministic path be a *real* path rather than a degraded one. And it
    gives the neutrality harness a fixed evidence set: a perturbation test is
    meaningless if the evidence moves between the control run and the perturbed
    one, so the evidence must not move.

    Results are derived from a content hash of the query, so the same query
    always yields the same items, different queries yield different ones, and
    nothing reads a clock or a random number generator. Every synthesised result
    carries ``is_fixture=True``, names a clearly fictional publisher and lives on
    a reserved ``.invalid`` host — a fixture must never be mistakable for a real
    publication.
    """

    name = "mock"

    def __init__(
        self,
        fixtures: Mapping[str, Sequence[SearchResult]] | None = None,
        *,
        default_count: int = 4,
        retrieved_at: str = "1970-01-01T00:00:00Z",
    ) -> None:
        self._fixtures = {self._key(key): list(value) for key, value in (fixtures or {}).items()}
        self._default_count = max(0, default_count)
        self._retrieved_at = retrieved_at
        """Fixed rather than "now": a bundle built from fixtures must be
        byte-identical between runs, and a timestamp is the easiest way to lose
        that."""

    @staticmethod
    def _key(text: str) -> str:
        return " ".join(_tokens(text))

    def search(
        self,
        query: str | GeneratedQuery | SearchQuery,
        *,
        limit: int = 10,
        since: str | date | datetime | None = None,
        until: str | date | datetime | None = None,
        language: str | None = None,
        allow_network: bool = False,
    ) -> list[SearchResult]:
        request = SearchQuery.coerce(query)
        supplied = self._fixtures.get(self._key(request.text))
        results = list(supplied) if supplied is not None else self._synthesise(request)
        return self._finalise(
            results,
            limit=limit,
            since=since or request.date_from,
            until=until or request.date_to,
            language=language,
        )

    def _synthesise(self, request: SearchQuery) -> list[SearchResult]:
        """Build a stable, obviously-synthetic result set for one query."""
        out: list[SearchResult] = []
        stem = " ".join(request.terms[:6]) or "query"
        for index in range(self._default_count):
            digest = stable_hash("aleph.search.mock", request.text, index, length=12)
            publisher, tier, independence = _FIXTURE_PUBLISHERS[
                int(digest[:2], 16) % len(_FIXTURE_PUBLISHERS)
            ]
            if request.expected_tier is not None and index == 0:
                tier = request.expected_tier
            day = 1 + int(digest[2:4], 16) % 28
            month = 1 + int(digest[4:6], 16) % 12
            out.append(
                SearchResult(
                    url=f"https://fixture.invalid/{stable_hash(request.text, length=8)}/{digest}",
                    title=f"[FIXTURE] {publisher} item on {stem}",
                    snippet=(
                        "Synthetic search result generated offline by Aleph's deterministic "
                        "mock provider. It describes no real publication and quotes no real "
                        f"person or outlet. Query: {request.text}"
                    ),
                    published_at=f"2026-{month:02d}-{day:02d}T09:00:00Z",
                    publisher=publisher,
                    language=request.language,
                    tier=tier,
                    independence=independence,
                    source_entry_id=(
                        request.source_ids[index % len(request.source_ids)]
                        if request.source_ids
                        else None
                    ),
                    provider=self.name,
                    retrieved_at=self._retrieved_at,
                    score=round(1.0 - index * 0.1, 3),
                    is_fixture=True,
                    raw={"synthetic": True, "index": index},
                )
            )
        return out


# ---------------------------------------------------------------------------
# Politeness scaffolding
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RateLimiter:
    """Per-host request spacing.

    Politeness, not performance. A registry entry that gets Aleph blocked removes
    a source from every future analysis, so the default interval is generous and
    per-host overrides from :class:`~aleph.core.models.RateLimit` are honoured.

    ``clock`` and ``sleep`` are injected so tests can drive the limiter without
    actually waiting — and so that a caller running inside an event loop can
    substitute a non-blocking wait.
    """

    default_interval: float = 1.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last: dict[str, float] = field(default_factory=dict)
    _intervals: dict[str, float] = field(default_factory=dict)

    def configure(self, host: str, interval: float | None) -> None:
        if interval and interval > 0:
            self._intervals[host] = interval

    def acquire(self, host: str) -> float:
        """Block until this host may be contacted again. Returns seconds waited."""
        interval = self._intervals.get(host, self.default_interval)
        now = self.clock()
        previous = self._last.get(host)
        waited = 0.0
        if previous is not None:
            remaining = interval - (now - previous)
            if remaining > 0:
                self.sleep(remaining)
                waited = remaining
        self._last[host] = self.clock()
        return waited


class RobotsGate:
    """Decides whether Aleph may fetch a URL, and refuses when it does not know.

    ``crawl_allowed=None`` in a registry entry means *not yet checked*, which is
    not the same as permitted — so an unchecked host is refused unless robots.txt
    can actually be read. Under ``manual`` retrieval that check itself requires
    network permission, which means the honest offline answer is "cannot fetch",
    and that is the answer this class gives.

    Rules can also be seeded from disk or from a test without any network at all.
    """

    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._parsers: dict[str, RobotFileParser] = {}
        self._unavailable: set[str] = set()

    @staticmethod
    def origin(url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, "", "", ""))

    def robots_url(self, url: str) -> str:
        return f"{self.origin(url)}/robots.txt"

    def seed(self, origin: str, robots_text: str) -> None:
        """Install robots rules for an origin without fetching anything."""
        parser = RobotFileParser()
        parser.parse(robots_text.splitlines())
        self._parsers[origin] = parser
        self._unavailable.discard(origin)

    def mark_unavailable(self, origin: str) -> None:
        """Record that robots.txt could not be read.

        A host whose policy is unknown is treated as disallowed. The alternative
        — assuming permission because a file was missing — is how a crawler ends
        up somewhere it was asked not to be.
        """
        self._unavailable.add(origin)

    def known(self, url: str) -> bool:
        origin = self.origin(url)
        return origin in self._parsers or origin in self._unavailable

    def can_fetch(self, url: str, *, entry: SourceRegistryEntry | None = None) -> bool:
        policy = entry.robots_policy if entry else None
        if policy is not None and policy.respect_robots is False:
            # Only ever set deliberately, for a source that has granted access in
            # writing. Recorded in the registry so the exception is auditable
            # rather than living in a fetcher's conditionals.
            return True
        if policy is not None and policy.crawl_allowed is False:
            return False
        origin = self.origin(url)
        parser = self._parsers.get(origin)
        if parser is not None:
            return bool(parser.can_fetch(self.user_agent, url))
        if origin in self._unavailable:
            return False
        return policy is not None and policy.crawl_allowed is True


@dataclass(frozen=True, slots=True)
class CachedResponse:
    """One stored response, with what a conditional request needs to revalidate."""

    url: str
    status: int
    body: bytes
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None
    fetched_at: str | None = None
    from_cache: bool = False

    def text(self, fallback: str = "utf-8") -> str:
        encoding = fallback
        if self.content_type and "charset=" in self.content_type:
            encoding = self.content_type.split("charset=", 1)[1].split(";")[0].strip() or fallback
        try:
            return self.body.decode(encoding, errors="replace")
        except LookupError:
            return self.body.decode(fallback, errors="replace")


class HttpCache:
    """On-disk response cache keyed by a hash of the URL.

    The cache is what makes a re-run cheap for the *source* rather than for
    Aleph: with a stored ``ETag`` a repeat fetch costs the server a 304 and no
    body. It is also what lets retrieval work at all under ``manual`` mode, where
    a cached response may be served but a new request may not be made.

    Metadata and body are stored side by side so a cache entry is inspectable by
    hand — a bundle that cites a source should be checkable without running the
    pipeline.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _stem(self, url: str) -> Path:
        return self.root / stable_hash("aleph.http", url, length=32)

    def get(self, url: str) -> CachedResponse | None:
        stem = self._stem(url)
        meta_path, body_path = stem.with_suffix(".meta"), stem.with_suffix(".body")
        if not (meta_path.exists() and body_path.exists()):
            return None
        try:
            meta = dict(
                line.split("\t", 1)  # type: ignore[misc]
                for line in meta_path.read_text(encoding="utf-8").splitlines()
                if "\t" in line
            )
            body = body_path.read_bytes()
        except OSError:
            return None
        return CachedResponse(
            url=meta.get("url", url),
            status=int(meta.get("status", "200")),
            body=body,
            etag=meta.get("etag") or None,
            last_modified=meta.get("last_modified") or None,
            content_type=meta.get("content_type") or None,
            fetched_at=meta.get("fetched_at") or None,
            from_cache=True,
        )

    def put(self, response: CachedResponse) -> None:
        stem = self._stem(response.url)
        stem.parent.mkdir(parents=True, exist_ok=True)
        fields = {
            "url": response.url,
            "status": str(response.status),
            "etag": response.etag or "",
            "last_modified": response.last_modified or "",
            "content_type": response.content_type or "",
            "fetched_at": response.fetched_at or "",
        }
        stem.with_suffix(".meta").write_text(
            "\n".join(f"{k}\t{v}" for k, v in fields.items()), encoding="utf-8"
        )
        stem.with_suffix(".body").write_bytes(response.body)


class PoliteFetcher:
    """The only place in Aleph that may issue an outbound request.

    Concentrated here so that every rule applies to every fetch: retrieval-mode
    gating, robots, per-host spacing, conditional revalidation, cache write, and
    a refusal to reach past a hard paywall. A second fetch path would inevitably
    implement four of the six.

    ``httpx`` is imported inside :meth:`fetch` rather than at module scope, so
    importing this module costs nothing and cannot fail on an environment where
    the HTTP client is unavailable but the offline pipeline is all that is wanted.
    """

    def __init__(
        self,
        *,
        config: Config | None = None,
        cache: HttpCache | None = None,
        rate_limiter: RateLimiter | None = None,
        robots: RobotsGate | None = None,
        transport: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config or get_config()
        self.cache = cache or HttpCache(self.config.cache_dir)
        self.rate_limiter = rate_limiter or RateLimiter(
            default_interval=self.config.fetch_delay_seconds
        )
        self.robots = robots or RobotsGate(self.config.user_agent)
        self._transport = transport
        """Injection point for tests: a callable with httpx's ``get`` signature.
        Supplying one keeps the whole class exercisable with no network."""

    # -- permissions --------------------------------------------------------

    def network_permitted(self, allow_network: bool) -> bool:
        """Whether an outbound request may happen at all.

        ``auto`` mode permits it; ``manual`` and ``on_demand`` require the caller
        to have said so explicitly at this call site. The asymmetry is the point:
        enabling retrieval is a deliberate act, and forgetting to enable it is a
        loud failure rather than a silent request.
        """
        return bool(allow_network) or self.config.retrieval_mode is RetrievalMode.AUTO

    # -- fetching -----------------------------------------------------------

    def fetch(
        self,
        url: str,
        *,
        allow_network: bool = False,
        entry: SourceRegistryEntry | None = None,
        is_feed: bool = False,
        max_bytes: int = _MAX_FEED_BYTES,
    ) -> CachedResponse:
        """Return the body at ``url``, from cache where possible.

        Raises:
            RetrievalDisabledError: Network is not permitted and nothing is cached.
            RetrievalError: robots.txt disallows the URL, the source is behind a
                hard paywall, the response was too large, or the request failed.
                Callers are expected to turn these into recorded retrieval gaps —
                a source that could not be read is a fact about the evidence base
                that a reader is entitled to see.
        """
        cached = self.cache.get(url)
        if not self.network_permitted(allow_network):
            if cached is not None:
                return cached
            raise RetrievalDisabledError(
                "retrieval is disabled for this run and the URL is not cached",
                mode=self.config.retrieval_mode.value,
                operation="fetch",
                url=url,
                source_id=entry.id if entry else None,
            )

        if entry is not None and entry.paywall is not None and entry.paywall.value == "hard":
            if not is_feed:
                raise RetrievalError(
                    "source is behind a hard paywall; Aleph does not circumvent access controls",
                    url=url,
                    source_id=entry.id,
                    reason="paywall",
                    retryable=False,
                )

        self._ensure_robots(url, allow_network=allow_network, entry=entry)
        if not self.robots.can_fetch(url, entry=entry):
            raise RetrievalError(
                "robots.txt does not permit this fetch",
                url=url,
                source_id=entry.id if entry else None,
                reason="robots_disallow",
                retryable=False,
            )

        host = urlsplit(url).netloc
        if entry is not None and entry.rate_limit is not None:
            self.rate_limiter.configure(host, entry.rate_limit.min_interval_seconds)
        self.rate_limiter.acquire(host)

        headers = {"User-Agent": self.config.user_agent, "Accept-Encoding": "gzip, deflate"}
        if cached is not None and cached.etag:
            headers["If-None-Match"] = cached.etag
        if cached is not None and cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified

        response = self._get(url, headers=headers)
        status = int(getattr(response, "status_code", 0))
        if status == 304 and cached is not None:
            return cached
        if status != 200:
            raise RetrievalError(
                f"unexpected HTTP status {status}",
                url=url,
                source_id=entry.id if entry else None,
                status_code=status,
                reason="http_status",
                retryable=status in {408, 429, 500, 502, 503, 504},
            )

        body = bytes(getattr(response, "content", b"") or b"")
        if len(body) > max_bytes:
            raise RetrievalError(
                "response exceeded the configured size limit and was discarded rather "
                "than truncated; a truncated feed produces a confidently incomplete result",
                url=url,
                source_id=entry.id if entry else None,
                reason="too_large",
                retryable=False,
            )
        response_headers = dict(getattr(response, "headers", {}) or {})
        lowered = {str(k).lower(): str(v) for k, v in response_headers.items()}
        stored = CachedResponse(
            url=url,
            status=status,
            body=body,
            etag=lowered.get("etag"),
            last_modified=lowered.get("last-modified"),
            content_type=lowered.get("content-type"),
            fetched_at=_utc(datetime.now(tz=UTC)),
        )
        self.cache.put(stored)
        return stored

    def _get(self, url: str, *, headers: Mapping[str, str]) -> Any:
        if self._transport is not None:
            return self._transport(url, headers=dict(headers))
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - httpx is a declared dependency
            raise RetrievalError(
                "no HTTP client is available in this environment",
                url=url,
                reason="no_transport",
                retryable=False,
            ) from exc
        try:
            return httpx.get(
                url,
                headers=dict(headers),
                timeout=self.config.request_timeout,
                follow_redirects=True,
            )
        except Exception as exc:  # noqa: BLE001 - transport failures are expected
            raise RetrievalError(
                "HTTP request failed",
                url=url,
                reason="transport_error",
                retryable=True,
            ) from exc

    def _ensure_robots(
        self, url: str, *, allow_network: bool, entry: SourceRegistryEntry | None
    ) -> None:
        """Load robots.txt for the URL's origin if it is not already known."""
        if self.robots.known(url):
            return
        policy = entry.robots_policy if entry else None
        if policy is not None and (policy.crawl_allowed is not None or not policy.respect_robots):
            return
        robots_url = (policy.robots_url if policy and policy.robots_url else None) or (
            self.robots.robots_url(url)
        )
        origin = self.robots.origin(url)
        cached = self.cache.get(robots_url)
        if cached is not None:
            self.robots.seed(origin, cached.text())
            return
        if not self.network_permitted(allow_network):
            self.robots.mark_unavailable(origin)
            return
        self.rate_limiter.acquire(urlsplit(robots_url).netloc)
        try:
            response = self._get(robots_url, headers={"User-Agent": self.config.user_agent})
        except RetrievalError:
            self.robots.mark_unavailable(origin)
            return
        status = int(getattr(response, "status_code", 0))
        body = bytes(getattr(response, "content", b"") or b"")
        if status == 200:
            stored = CachedResponse(
                url=robots_url,
                status=status,
                body=body,
                content_type="text/plain",
                fetched_at=_utc(datetime.now(tz=UTC)),
            )
            self.cache.put(stored)
            self.robots.seed(origin, stored.text())
        elif status in {401, 403}:
            # An access-controlled robots.txt is a refusal, not an absence.
            self.robots.mark_unavailable(origin)
        elif status == 404:
            # No policy published: the convention is that everything is allowed.
            self.robots.seed(origin, "")
        else:
            self.robots.mark_unavailable(origin)


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, *names: str) -> str | None:
    wanted = {n.lower() for n in names}
    for child in element:
        if _local(child.tag) in wanted:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return None


def _link_of(element: ET.Element) -> str | None:
    """Extract an item's URL from whichever convention the feed uses."""
    for child in element:
        if _local(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        rel = (child.attrib.get("rel") or "alternate").lower()
        if href and rel == "alternate":
            return href.strip()
        text = (child.text or "").strip()
        if text:
            return text
    for child in element:
        if _local(child.tag) in {"guid", "id", "loc"}:
            text = (child.text or "").strip()
            if text.startswith("http"):
                return text
    return None


def parse_feed(payload: bytes | str, *, base_url: str | None = None) -> list[dict[str, Any]]:
    """Parse an RSS, Atom or sitemap document into plain item dictionaries.

    Feeds are preferred over HTML scraping throughout Aleph: a declared feed is
    what a publisher offers for machine consumption, it is more complete than a
    front page, and polling it is far less intrusive than crawling.

    Documents declaring a doctype or an entity are refused outright. No
    legitimate feed needs either, and an internal entity definition is the entire
    mechanism of the classic XML expansion attack.

    Returns:
        Dictionaries with ``url``, ``title``, ``summary`` and ``published_at``.
        Malformed XML yields an empty list rather than raising: a broken feed is
        a retrieval gap to record, not a reason to abort a phase.
    """
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if _XML_DOCTYPE_RE.search(raw[:4096]):
        return []
    try:
        root = ET.fromstring(raw)  # noqa: S314 - doctype/entity refused above
    except ET.ParseError:
        return []

    items: list[dict[str, Any]] = []
    for element in root.iter():
        tag = _local(element.tag)
        if tag not in {"item", "entry", "url"}:
            continue
        url = _link_of(element)
        if not url:
            continue
        if base_url and url.startswith("/"):
            parts = urlsplit(base_url)
            url = urlunsplit((parts.scheme, parts.netloc, url, "", ""))
        title = _child_text(element, "title", "name") or url
        summary = _child_text(element, "description", "summary", "content", "subtitle") or ""
        published = _parse_datetime(
            _child_text(element, "pubdate", "published", "updated", "lastmod", "date")
        )
        items.append(
            {
                "url": url,
                "title": _strip_markup(title),
                "summary": _strip_markup(summary),
                "published_at": published,
            }
        )
    return items


# ---------------------------------------------------------------------------
# Registry-driven provider
# ---------------------------------------------------------------------------


class RegistryFeedProvider(SearchProvider):
    """Discovers items from the declared feeds of registered sources.

    This is Aleph's real retrieval path, and it is deliberately narrow: it reads
    the RSS, Atom and sitemap endpoints a publisher has declared, and it does not
    crawl. Matching is a transparent term-overlap score over each item's title
    and summary rather than a ranking model, because the ranking has to be
    explicable — an evidence base assembled by an opaque scorer cannot be audited
    for what it left out.

    Routing honours the query's ``target_source_ids`` when phase 4 set them, so a
    query aimed at a statistics agency is not answered by a news feed. Registry
    entries carry no credibility field and this class introduces none: the only
    things read off an entry are how to reach it, what kind of artefact it
    produces, and how politely to treat it.
    """

    name = "registry_feed"

    def __init__(
        self,
        entries: Sequence[SourceRegistryEntry],
        *,
        fetcher: PoliteFetcher | None = None,
        kinds: Iterable[SourceKind] | None = None,
        min_score: float = 0.34,
    ) -> None:
        self.entries = [entry for entry in entries if entry.enabled]
        self.fetcher = fetcher or PoliteFetcher()
        self.kinds = set(kinds) if kinds is not None else None
        self.min_score = min_score
        self.gaps: list[RetrievalError] = []
        """Failures from the last search, for the caller to record as retrieval
        gaps. A source that could not be read is evidence about the evidence
        base, and swallowing it would make a thin analysis look thorough."""

    def search(
        self,
        query: str | GeneratedQuery | SearchQuery,
        *,
        limit: int = 10,
        since: str | date | datetime | None = None,
        until: str | date | datetime | None = None,
        language: str | None = None,
        allow_network: bool = False,
    ) -> list[SearchResult]:
        request = SearchQuery.coerce(query)
        self.gaps = []
        results: list[SearchResult] = []

        for entry in self._entries_for(request):
            for feed in entry.feeds:
                if not feed.enabled or feed.auth_required:
                    continue
                results.extend(self._search_feed(entry, feed, request, allow_network=allow_network))

        return self._finalise(
            results,
            limit=limit,
            since=since or request.date_from,
            until=until or request.date_to,
            language=language,
        )

    def _entries_for(self, request: SearchQuery) -> list[SourceRegistryEntry]:
        wanted = set(request.source_ids)
        selected = [
            entry
            for entry in self.entries
            if (not wanted or entry.id in wanted)
            and (self.kinds is None or entry.kind in self.kinds)
        ]
        return sorted(selected, key=lambda e: e.id)

    def _search_feed(
        self,
        entry: SourceRegistryEntry,
        feed: Feed,
        request: SearchQuery,
        *,
        allow_network: bool,
    ) -> list[SearchResult]:
        try:
            response = self.fetcher.fetch(
                feed.url, allow_network=allow_network, entry=entry, is_feed=True
            )
        except RetrievalError as exc:
            # Recorded rather than raised: one unreachable feed must not abort a
            # search across a dozen sources, and the gap is itself a finding.
            self.gaps.append(exc)
            return []

        out: list[SearchResult] = []
        for item in parse_feed(response.text(), base_url=entry.base_url):
            score = _match_score(request, item["title"], item["summary"])
            if score < self.min_score:
                continue
            out.append(
                SearchResult(
                    url=item["url"],
                    title=item["title"],
                    snippet=item["summary"][:600],
                    published_at=item["published_at"],
                    publisher=entry.name,
                    language=feed.language or entry.language,
                    tier=entry.evidence_tier,
                    independence=entry.typical_independence,
                    source_entry_id=entry.id,
                    provider=self.name,
                    retrieved_at=response.fetched_at,
                    score=score,
                    raw={"feed_url": feed.url, "feed_format": feed.format.value},
                )
            )
        return out


def _match_score(request: SearchQuery, title: str, summary: str) -> float:
    """How well one feed item answers one query, explicably.

    Term overlap with a bonus for exact phrase matches and a bonus for a hit in
    the title. Deliberately simple: every number in an Aleph result must be
    reconstructible by hand, and a relevance score a reader cannot recompute is
    an unauditable filter on what evidence reaches them.
    """
    terms = request.terms
    if not terms:
        return 0.0
    haystack_title = _fold(title)
    haystack = f"{haystack_title} {_fold(summary)}"
    tokens = set(_tokens(haystack))
    hits = sum(1 for term in terms if term in tokens)
    score = hits / len(terms)
    for phrase in request.phrases:
        if _fold(phrase) in haystack:
            score += 0.25
    if any(term in _tokens(haystack_title) for term in terms):
        score += 0.1
    return round(min(1.0, score), 3)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_search_provider(
    *,
    config: Config | None = None,
    entries: Sequence[SourceRegistryEntry] = (),
    fetcher: PoliteFetcher | None = None,
) -> SearchProvider:
    """Build the provider named by configuration.

    Defaults to the deterministic mock, so an unconfigured deployment runs
    offline and reproducibly rather than failing or reaching for the network.
    ``registry_feed`` is selected explicitly, and even then it emits nothing
    until a caller passes ``allow_network=True``.
    """
    resolved = config or get_config()
    provider = (resolved.search_provider or "mock").strip().lower()
    if provider in {"none", "off", "disabled"}:
        return NullSearchProvider()
    if provider in {"registry", "registry_feed", "feeds", "http"}:
        return RegistryFeedProvider(entries, fetcher=fetcher or PoliteFetcher(config=resolved))
    return DeterministicMockProvider()
