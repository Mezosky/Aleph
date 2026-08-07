"""Polite, append-only acquisition of registered news feeds and article snapshots."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select

from aleph.core.enums import SourceKind
from aleph.core.errors import RetrievalError
from aleph.news.registry import SourceRegistryStore, load_registry
from aleph.retrieval.search import CachedResponse, PoliteFetcher, parse_feed
from api.database import (
    Database,
    DiscoveredNewsRow,
    RetrievalSnapshotRow,
    ScrapeRunRow,
    utcnow,
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.-]+")


def _id() -> str:
    return uuid.uuid4().hex


def _instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _fold(value: str) -> str:
    normal = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normal if not unicodedata.combining(character))


def _query_terms(query: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_TOKEN_RE.findall(_fold(query))))


def _relevance(
    query_terms: tuple[str, ...], title: str, summary: str, url: str
) -> tuple[float, list[str]]:
    haystack = _fold(f"{title} {summary} {url}")
    matched = [term for term in query_terms if term in haystack]
    if not query_terms:
        return 0.0, []
    title_folded = _fold(title)
    score = len(matched) / len(query_terms)
    if any(term in title_folded for term in matched):
        score += 0.2
    return round(min(score, 1.0), 3), matched


def _same_publisher_host(article_url: str, base_url: str) -> bool:
    article_host = (urlsplit(article_url).hostname or "").casefold()
    base_host = (urlsplit(base_url).hostname or "").casefold().removeprefix("www.")
    return article_host == base_host or article_host.endswith(f".{base_host}")


@dataclass(frozen=True, slots=True)
class AcquisitionSummary:
    run_id: str
    sources_total: int
    sources_checked: int
    feed_snapshots: int
    items_seen: int
    items_new: int
    relevant_items: int
    article_snapshots: int
    failures: int


class NewsAcquirer:
    """Poll declared feeds, preserve exact bytes, and fetch only matching articles."""

    def __init__(
        self,
        database: Database,
        *,
        registry: SourceRegistryStore | None = None,
        fetcher: PoliteFetcher | None = None,
    ) -> None:
        self.database = database
        self.registry = registry or load_registry()
        self.fetcher = fetcher or PoliteFetcher()

    def run(
        self,
        query: str,
        *,
        allow_network: bool = False,
        max_articles: int = 20,
    ) -> AcquisitionSummary:
        if not allow_network:
            raise ValueError("live news acquisition requires allow_network=True")
        entries = [
            entry
            for entry in self.registry
            if entry.enabled
            and entry.kind is SourceKind.NEWS_OUTLET
            and entry.feeds
            and self.registry.is_verified(entry.id)
        ]
        run_id = _id()
        now = utcnow()
        with self.database.sessions.begin() as session:
            session.add(
                ScrapeRunRow(
                    id=run_id,
                    query=query,
                    state="running",
                    sources_total=len(entries),
                    started_at=now,
                    updated_at=now,
                )
            )

        terms = _query_terms(query)
        articles_left = max(0, max_articles)
        for entry in entries:
            for feed in entry.feeds:
                if not feed.enabled or feed.auth_required:
                    continue
                try:
                    response = self.fetcher.fetch(
                        feed.url,
                        allow_network=True,
                        entry=entry,
                        is_feed=True,
                    )
                    feed_snapshot_id = self._snapshot(run_id, entry.id, "feed", response)
                    items = parse_feed(response.body, base_url=entry.base_url)
                    for item in items:
                        score, matched = _relevance(
                            terms,
                            item["title"],
                            item["summary"],
                            item["url"],
                        )
                        row, is_new = self._observe(
                            entry.id,
                            feed_snapshot_id,
                            item,
                            score,
                            matched,
                        )
                        self._increment(run_id, "items_seen")
                        if is_new:
                            self._increment(run_id, "items_new")
                        if not matched:
                            continue
                        self._increment(run_id, "relevant_items")
                        if (
                            articles_left > 0
                            and row.article_snapshot_id is None
                            and _same_publisher_host(row.url, entry.base_url)
                        ):
                            try:
                                article = self.fetcher.fetch(
                                    row.url,
                                    allow_network=True,
                                    entry=entry,
                                    max_bytes=5 * 1024 * 1024,
                                )
                                article_snapshot_id = self._snapshot(
                                    run_id, entry.id, "article", article
                                )
                                with self.database.sessions.begin() as session:
                                    stored = session.get(DiscoveredNewsRow, row.id)
                                    if stored is not None:
                                        stored.article_snapshot_id = article_snapshot_id
                                self._increment(run_id, "article_snapshots")
                                articles_left -= 1
                            except RetrievalError as exc:
                                self._failure(run_id, entry.id, row.url, exc)
                except RetrievalError as exc:
                    self._failure(run_id, entry.id, feed.url, exc)
            self._increment(run_id, "sources_checked")

        completed = utcnow()
        with self.database.sessions.begin() as session:
            run = session.get(ScrapeRunRow, run_id)
            if run is None:
                raise RuntimeError("scrape run disappeared while executing")
            run.state = "complete"
            run.completed_at = completed
            run.updated_at = completed
            return AcquisitionSummary(
                run_id=run.id,
                sources_total=run.sources_total,
                sources_checked=run.sources_checked,
                feed_snapshots=run.feed_snapshots,
                items_seen=run.items_seen,
                items_new=run.items_new,
                relevant_items=run.relevant_items,
                article_snapshots=run.article_snapshots,
                failures=len(run.failures),
            )

    def _snapshot(
        self,
        run_id: str,
        source_id: str,
        resource_kind: str,
        response: CachedResponse,
    ) -> str:
        digest = hashlib.sha256(response.body).hexdigest()
        with self.database.sessions.begin() as session:
            existing = session.scalar(
                select(RetrievalSnapshotRow).where(
                    RetrievalSnapshotRow.url == response.url,
                    RetrievalSnapshotRow.content_sha256 == digest,
                )
            )
            if existing is not None:
                snapshot_id = existing.id
            else:
                snapshot_id = _id()
                session.add(
                    RetrievalSnapshotRow(
                        id=snapshot_id,
                        scrape_run_id=run_id,
                        source_id=source_id,
                        resource_kind=resource_kind,
                        url=response.url,
                        content_sha256=digest,
                        content=response.body,
                        size_bytes=len(response.body),
                        status_code=response.status,
                        content_type=response.content_type,
                        etag=response.etag,
                        last_modified=response.last_modified,
                        fetched_at=_instant(response.fetched_at) or utcnow(),
                    )
                )
        self._increment(run_id, "feed_snapshots" if resource_kind == "feed" else None)
        return snapshot_id

    def _observe(
        self,
        source_id: str,
        feed_snapshot_id: str,
        item: dict,
        score: float,
        matched: list[str],
    ) -> tuple[DiscoveredNewsRow, bool]:
        now = utcnow()
        with self.database.sessions.begin() as session:
            row = session.scalar(
                select(DiscoveredNewsRow).where(DiscoveredNewsRow.url == item["url"])
            )
            is_new = row is None
            if row is None:
                row = DiscoveredNewsRow(
                    id=_id(),
                    source_id=source_id,
                    url=item["url"],
                    title=item["title"],
                    summary=item["summary"],
                    published_at=_instant(item.get("published_at")),
                    first_seen_at=now,
                    last_seen_at=now,
                    feed_snapshot_id=feed_snapshot_id,
                    relevance_score=score,
                    matched_terms=matched,
                    raw_metadata=item,
                )
                session.add(row)
            else:
                row.last_seen_at = now
                row.title = item["title"]
                row.summary = item["summary"]
                row.relevance_score = score
                row.matched_terms = matched
                row.raw_metadata = item
            session.flush()
            session.expunge(row)
            return row, is_new

    def _increment(self, run_id: str, field: str | None) -> None:
        if field is None:
            return
        with self.database.sessions.begin() as session:
            run = session.get(ScrapeRunRow, run_id)
            if run is not None:
                setattr(run, field, getattr(run, field) + 1)
                run.updated_at = utcnow()

    def _failure(self, run_id: str, source_id: str, url: str, exc: Exception) -> None:
        with self.database.sessions.begin() as session:
            run = session.get(ScrapeRunRow, run_id)
            if run is not None:
                failures = list(run.failures)
                failures.append(
                    {
                        "source_id": source_id,
                        "url": url,
                        "error": type(exc).__name__,
                        "message": str(exc)[:500],
                    }
                )
                run.failures = failures
                run.updated_at = utcnow()
