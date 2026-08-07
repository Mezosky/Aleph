"""Capture the curated Megareforma source sweep for offline publication.

This script is deliberately opt-in. It checks robots.txt, saves exact response
bytes in Aleph's append-only retrieval store, and creates a reduced viewport
screenshot for the static dossier. The deployed site performs no requests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
import yaml
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.database import (  # noqa: E402
    Database,
    DiscoveredNewsRow,
    RetrievalSnapshotRow,
    ScrapeRunRow,
    utcnow,
)

MANIFEST = ROOT / "aleph/news/megareforma_sources.yaml"
OUT = ROOT / "frontend/public/data/megareforma"
SCREENSHOTS = OUT / "screenshots"
USER_AGENT = "Aleph/0.1 (+https://github.com/Mezosky/Aleph)"


def _id() -> str:
    return uuid.uuid4().hex


def _instant(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _robots_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


def _robots_allows(client: httpx.Client, url: str) -> tuple[bool, str]:
    robots_url = _robots_url(url)
    response = client.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=20)
    if response.status_code >= 400:
        return False, f"robots unavailable: HTTP {response.status_code}"
    parser = RobotFileParser(robots_url)
    parser.parse(response.text.splitlines())
    return parser.can_fetch(USER_AGENT, url), robots_url


def _meta(page, selector: str) -> str:
    element = page.locator(selector).first
    if element.count() == 0:
        return ""
    return (element.get_attribute("content") or "").strip()


def _snapshot(
    database: Database,
    *,
    run_id: str,
    source_id: str,
    url: str,
    content: bytes,
    status: int,
    content_type: str | None,
) -> str:
    digest = hashlib.sha256(content).hexdigest()
    with database.sessions.begin() as session:
        existing = session.scalar(
            select(RetrievalSnapshotRow).where(
                RetrievalSnapshotRow.url == url,
                RetrievalSnapshotRow.content_sha256 == digest,
            )
        )
        if existing is not None:
            return existing.id
        snapshot_id = _id()
        session.add(
            RetrievalSnapshotRow(
                id=snapshot_id,
                scrape_run_id=run_id,
                source_id=source_id,
                resource_kind="article",
                url=url,
                content_sha256=digest,
                content=content,
                size_bytes=len(content),
                status_code=status,
                content_type=content_type,
                fetched_at=utcnow(),
            )
        )
        return snapshot_id


def _upsert_observation(
    database: Database,
    *,
    item: dict,
    snapshot_id: str,
    screenshot_path: str,
    screenshot_sha256: str,
) -> bool:
    now = utcnow()
    with database.sessions.begin() as session:
        existing = session.scalar(
            select(DiscoveredNewsRow).where(DiscoveredNewsRow.url == item["url"])
        )
        metadata = {
            "manifest_id": item["id"],
            "kind": item["kind"],
            "format": item.get("format", "article"),
            "perspective": item["perspective"],
            "screenshot_path": screenshot_path,
            "screenshot_sha256": screenshot_sha256,
        }
        if existing is not None:
            existing.last_seen_at = now
            existing.article_snapshot_id = snapshot_id
            existing.raw_metadata = {**dict(existing.raw_metadata), **metadata}
            return False
        session.add(
            DiscoveredNewsRow(
                id=_id(),
                source_id=f"src:dossier-{re.sub(r'[^a-z0-9]+', '-', item['publisher'].lower())}",
                url=item["url"],
                title=item["title"],
                summary=item["summary"],
                published_at=_instant(item.get("published_at")),
                first_seen_at=now,
                last_seen_at=now,
                feed_snapshot_id=snapshot_id,
                article_snapshot_id=snapshot_id,
                relevance_score=1.0,
                matched_terms=["18216-05", "megareforma"],
                raw_metadata=metadata,
            )
        )
        return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-network", action="store_true", required=True)
    parser.add_argument("--database-url", default="sqlite:///./data/aleph.db")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--start-at",
        type=int,
        default=0,
        help="Resume at this zero-based manifest index and retain earlier exported results.",
    )
    args = parser.parse_args()

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    seeds = list(manifest["sources"])
    previous_results: list[dict] = []
    previous_failures: list[dict] = []
    if args.start_at > 0:
        previous_path = OUT / "sources.json"
        if not previous_path.exists():
            raise SystemExit("--start-at requires an existing sources.json export")
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        retained_ids = {seed["id"] for seed in seeds[: args.start_at]}
        previous_results = [item for item in previous["items"] if item["id"] in retained_ids]
        previous_failures = [item for item in previous["gaps"] if item["id"] in retained_ids]
        seeds = seeds[args.start_at :]
    if args.limit > 0:
        seeds = seeds[: args.limit]
    OUT.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    database = Database(args.database_url)
    run_id = _id()
    started = utcnow()
    with database.sessions.begin() as session:
        session.add(
            ScrapeRunRow(
                id=run_id,
                query="Megareforma canonical sweep: 18216-05",
                state="running",
                sources_total=len(seeds),
                started_at=started,
                updated_at=started,
            )
        )

    results: list[dict] = list(previous_results)
    failures: list[dict] = list(previous_failures)
    processed = 0
    last_host = ""
    with httpx.Client(follow_redirects=True) as client, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            device_scale_factor=1,
            user_agent=USER_AGENT,
            locale="es-CL",
        )
        page = context.new_page()
        for seed in seeds:
            url = str(seed["url"])
            host = urlsplit(url).hostname or ""
            if host == last_host:
                time.sleep(2)
            last_host = host
            try:
                allowed, robots = _robots_allows(client, url)
                if not allowed:
                    raise RuntimeError(f"robots policy did not permit capture ({robots})")
                screenshot = SCREENSHOTS / f"{seed['id']}.jpg"
                if urlsplit(url).path.lower().endswith("verdoc.aspx"):
                    import pymupdf

                    landing = (
                        "https://www.camara.cl/legislacion/proyectosdeley/informes.aspx"
                        "?prmBOLETIN=18216-05&prmID=18872"
                    )
                    page.goto(landing, wait_until="domcontentloaded", timeout=60_000)
                    with page.expect_download(timeout=60_000) as download_info:
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                        except PlaywrightError as exc:
                            if "Download is starting" not in str(exc):
                                raise
                    download = download_info.value
                    download_path = download.path()
                    if download_path is None:
                        raise RuntimeError("official report download had no local payload")
                    body = Path(download_path).read_bytes()
                    if not body.startswith(b"%PDF"):
                        raise RuntimeError("official report endpoint did not download a PDF")
                    document = pymupdf.open(stream=body, filetype="pdf")
                    pixmap = document[0].get_pixmap(matrix=pymupdf.Matrix(1.35, 1.35), alpha=False)
                    pixmap.save(str(screenshot))
                    document.close()
                    status = 200
                    content_type = "application/pdf"
                    title = str(seed.get("title") or download.suggested_filename or seed["id"])
                    summary = str(
                        seed.get("summary")
                        or "Informe legislativo oficial conservado desde el expediente del proyecto."
                    )
                elif urlsplit(url).path.lower().endswith(".pdf"):
                    import pymupdf

                    pdf_response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
                    pdf_response.raise_for_status()
                    body = pdf_response.content
                    if not body.startswith(b"%PDF"):
                        raise RuntimeError("PDF endpoint did not return a PDF")
                    document = pymupdf.open(stream=body, filetype="pdf")
                    pixmap = document[0].get_pixmap(matrix=pymupdf.Matrix(1.35, 1.35), alpha=False)
                    pixmap.save(str(screenshot))
                    document.close()
                    status = pdf_response.status_code
                    content_type = pdf_response.headers.get("content-type")
                    title = str(seed.get("title") or seed["id"])
                    summary = str(
                        seed.get("summary")
                        or "Documento técnico conservado como referencia del expediente."
                    )
                else:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    if response is None:
                        raise RuntimeError("navigation returned no main response")
                    page.wait_for_timeout(1800)
                    body = response.body()
                    title = str(
                        seed.get("title")
                        or _meta(page, 'meta[property="og:title"]')
                        or page.title()
                        or seed["id"]
                    )
                    visible_text = page.locator("body").inner_text(timeout=10_000).lower()
                    blocked_markers = (
                        "el acceso está restringido temporalmente",
                        "ssl handshake failed",
                        "access denied",
                        "debe identificarse para acceder",
                    )
                    if response.status >= 400 or any(
                        marker in visible_text for marker in blocked_markers
                    ):
                        raise RuntimeError(
                            f"origin returned a blocked/error page (HTTP {response.status}, title={title!r})"
                        )
                    if title.strip().lower() in {"elpais.com", "access denied"}:
                        raise RuntimeError(
                            f"origin did not expose the article page (title={title!r})"
                        )
                    summary = str(
                        seed.get("summary")
                        or _meta(page, 'meta[property="og:description"]')
                        or _meta(page, 'meta[name="description"]')
                        or "Fuente relevante para el expediente de la Megareforma."
                    )
                    page.screenshot(path=str(screenshot), type="jpeg", quality=68, full_page=False)
                    status = response.status
                    content_type = response.headers.get("content-type")
                screenshot_bytes = screenshot.read_bytes()
                snapshot_id = _snapshot(
                    database,
                    run_id=run_id,
                    source_id=f"src:dossier-{seed['id']}",
                    url=url,
                    content=body,
                    status=status,
                    content_type=content_type,
                )
                item = {
                    **seed,
                    "title": title,
                    "summary": summary,
                    "snapshot_id": snapshot_id,
                    "screenshot": f"megareforma/screenshots/{screenshot.name}",
                    "screenshot_sha256": hashlib.sha256(screenshot_bytes).hexdigest(),
                    "captured_at": utcnow().isoformat().replace("+00:00", "Z"),
                    "original_url": url,
                }
                is_new = _upsert_observation(
                    database,
                    item=item,
                    snapshot_id=snapshot_id,
                    screenshot_path=item["screenshot"],
                    screenshot_sha256=item["screenshot_sha256"],
                )
                item["new_observation"] = is_new
                results.append(item)
                processed += 1
                print(f"[{processed}/{len(seeds)}] {seed['publisher']}: {title[:80]}", flush=True)
            except Exception as exc:  # noqa: BLE001 - every gap is retained
                failure = {"id": seed["id"], "url": url, "error": f"{type(exc).__name__}: {exc}"}
                failures.append(failure)
                processed += 1
                print(f"GAP {seed['id']}: {failure['error']}", flush=True)
            finally:
                with database.sessions.begin() as session:
                    run = session.get(ScrapeRunRow, run_id)
                    current_results = results[len(previous_results) :]
                    current_failures = failures[len(previous_failures) :]
                    run.sources_checked += 1
                    run.items_seen = len(current_results)
                    run.items_new = sum(bool(item["new_observation"]) for item in current_results)
                    run.relevant_items = len(current_results)
                    run.article_snapshots = len(current_results)
                    run.failures = list(current_failures)
                    run.updated_at = utcnow()
        context.close()
        browser.close()

    completed = utcnow()
    with database.sessions.begin() as session:
        run = session.get(ScrapeRunRow, run_id)
        run.state = "complete"
        run.completed_at = completed
        run.updated_at = completed
    output = {
        "schema_version": manifest["schema_version"],
        "document_id": manifest["document_id"],
        "retrieval_cutoff": manifest["retrieval_cutoff"],
        "scrape_run_id": run_id,
        "capture_count": len(results),
        "gap_count": len(failures),
        "items": results,
        "gaps": failures,
    }
    (OUT / "sources.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"run_id": run_id, "captured": len(results), "gaps": len(failures)}))
    database.dispose()
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
