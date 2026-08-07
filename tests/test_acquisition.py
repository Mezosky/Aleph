from __future__ import annotations

from sqlalchemy import func, select

from aleph.news.registry import SourceRegistryStore, load_registry
from aleph.retrieval.acquisition import NewsAcquirer
from aleph.retrieval.search import CachedResponse
from api.database import (
    Database,
    DiscoveredNewsRow,
    RetrievalSnapshotRow,
    ScrapeRunRow,
)


class _FixtureFetcher:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def fetch(self, url: str, **_kwargs) -> CachedResponse:
        self.urls.append(url)
        if "feedburner" in url:
            body = b"""<?xml version="1.0"?>
            <rss><channel>
              <item><title>Budget reform advances</title>
                <link>https://www.biobiochile.cl/noticias/budget-reform</link>
                <description>Economic budget proposal</description></item>
              <item><title>Sports result</title>
                <link>https://www.biobiochile.cl/noticias/sports</link>
                <description>Match report</description></item>
            </channel></rss>"""
            return CachedResponse(
                url=url,
                status=200,
                body=body,
                content_type="application/rss+xml",
                fetched_at="2026-08-07T12:00:00Z",
            )
        return CachedResponse(
            url=url,
            status=200,
            body=b"<html><body>Exact article bytes</body></html>",
            content_type="text/html; charset=utf-8",
            fetched_at="2026-08-07T12:00:01Z",
        )


def _one_verified_source() -> SourceRegistryStore:
    packaged = load_registry()
    entry = packaged.require("src:cl-biobiochile")
    return SourceRegistryStore.from_entries([entry], verified={entry.id: True})


def test_acquisition_requires_explicit_network_permission() -> None:
    database = Database("sqlite:///:memory:")
    acquirer = NewsAcquirer(database, registry=_one_verified_source(), fetcher=_FixtureFetcher())

    try:
        acquirer.run("budget reform")
    except ValueError as exc:
        assert "allow_network=True" in str(exc)
    else:  # pragma: no cover - safety contract must not regress silently
        raise AssertionError("acquisition ran without explicit network permission")


def test_acquisition_persists_bytes_and_deduplicates_repeat_observations() -> None:
    database = Database("sqlite:///:memory:")
    fetcher = _FixtureFetcher()
    acquirer = NewsAcquirer(database, registry=_one_verified_source(), fetcher=fetcher)

    first = acquirer.run("budget reform", allow_network=True, max_articles=1)
    second = acquirer.run("budget reform", allow_network=True, max_articles=1)

    assert first.sources_checked == 1
    assert first.items_seen == 2
    assert first.items_new == 2
    assert first.relevant_items == 1
    assert first.article_snapshots == 1
    assert second.items_seen == 2
    assert second.items_new == 0
    assert second.article_snapshots == 0
    with database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ScrapeRunRow)) == 2
        assert session.scalar(select(func.count()).select_from(DiscoveredNewsRow)) == 2
        assert session.scalar(select(func.count()).select_from(RetrievalSnapshotRow)) == 2
        article = session.scalar(
            select(RetrievalSnapshotRow).where(RetrievalSnapshotRow.resource_kind == "article")
        )
        assert article is not None
        assert article.content == b"<html><body>Exact article bytes</body></html>"
