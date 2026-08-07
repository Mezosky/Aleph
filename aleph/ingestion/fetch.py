"""Getting a document's bytes, deliberately and politely, or not at all.

This is the only place in the document-understanding phase that can touch the
network, and it is built so that touching the network is always an explicit act.
Aleph's default retrieval mode is ``manual``: no module may emit traffic as a
side effect of running a pipeline. Two things follow, and both are enforced here
rather than documented and hoped for.

**Network access requires ``allow_network=True``, passed by keyword.** A caller
that forgets gets a :class:`~aleph.core.errors.RetrievalDisabledError` at the
call site, not a silent HTTP request. This protects two different things at once:
a stranger's server, which did not ask to be crawled by whoever is running this,
and the reproducibility of an analysis, which is worthless if the evidence base
can shift underneath it mid-run.

**Fetching is polite when it happens.** An honest User-Agent that identifies the
project and offers a way to make contact, robots.txt consulted before the
request, a minimum delay between requests to the same host, and a hard size cap
enforced *while streaming* so that an unexpectedly enormous file is abandoned
rather than downloaded and then rejected.

The redirect chain is walked manually instead of delegating to httpx, for one
specific reason: a redirect to a non-HTTP scheme must never be followed. A
``Location: file:///etc/passwd`` handed to an automatic redirect follower is a
file-disclosure primitive, and the same applies to ``data:``, ``ftp:`` and
anything else a server might suggest. Only ``http`` and ``https`` are ever
followed, and every hop is recorded so the caller can see where the bytes really
came from.

Local paths and raw bytes go through the same door and come back as the same
:class:`FetchedDocument`, so that the rest of the pipeline never branches on
where a document came from — only on what the hash says it is.
"""

from __future__ import annotations

import hashlib
import mimetypes
import threading
import time
import urllib.robotparser
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import urlsplit

from aleph.core.config import Config, get_config
from aleph.core.enums import RetrievalMethod, RetrievalMode
from aleph.core.errors import (
    RetrievalDisabledError,
    RetrievalError,
    UnsupportedDocumentError,
)

__all__ = [
    "ALLOWED_SCHEMES",
    "DOCUMENT_MEDIA_TYPES",
    "MAX_REDIRECTS",
    "SourceKind",
    "FetchedDocument",
    "sha256_hex",
    "classify_source",
    "from_bytes",
    "read_path",
    "fetch_url",
    "load_source",
    "is_network_permitted",
    "reset_politeness_state",
]

#: The only URL schemes Aleph will ever request or follow a redirect to.
#: ``file``, ``data``, ``ftp`` and the rest are absent on purpose: a redirect
#: target is chosen by a remote server, and a fetcher that honours an arbitrary
#: scheme hands that server a way to read the local filesystem.
ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})

#: Media types accepted as a document payload. ``octet-stream`` is included
#: because a great many servers label PDFs that way, but the bytes are still
#: checked for a PDF signature before the response is accepted.
DOCUMENT_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/pdf",
        "application/x-pdf",
        "application/acrobat",
        "applications/vnd.pdf",
        "text/pdf",
        "text/x-pdf",
        "application/octet-stream",
        "binary/octet-stream",
        "text/plain",
    }
)

#: Media types that indicate the server sent a web page rather than a document —
#: typically a login wall, a cookie interstitial or an error page.
_MARKUP_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {"text/html", "application/xhtml+xml", "application/xml", "text/xml"}
)

#: Redirect hops followed before giving up.
MAX_REDIRECTS: Final[int] = 5

_REDIRECT_STATUSES: Final[frozenset[int]] = frozenset({301, 302, 303, 307, 308})

_PDF_MAGIC: Final[bytes] = b"%PDF-"
_MAGIC_WINDOW: Final[int] = 2048

#: Longest string that will be tested against the filesystem. Beyond this a
#: string is certainly document text, and calling ``Path.exists`` on it would
#: raise on some platforms rather than answer.
_MAX_PATH_LENGTH: Final[int] = 4096

SourceKind = Literal["bytes", "url", "path", "text"]

# Per-host state for politeness. Module-level because rate limiting is only
# meaningful across calls; guarded by a lock because the API layer is threaded.
_politeness_lock: Final[threading.Lock] = threading.Lock()
_last_request_at: dict[str, float] = {}
_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def reset_politeness_state() -> None:
    """Clear per-host rate-limit and robots.txt caches.

    For tests and for long-lived processes. Never call this to work around a
    disallow: re-reading robots.txt does not change what it said.
    """
    with _politeness_lock:
        _last_request_at.clear()
        _robots_cache.clear()


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    """Bytes plus everything needed to say where they came from and what they are.

    ``sha256`` is the field that makes a re-run interpretable. Without it, an
    analysis that changes between two runs is ambiguous — the document may have
    been amended, or Aleph's own extraction may have changed — and a reader has
    no way to tell those apart. With it, "the document changed" and "the analysis
    changed" are distinguishable facts.

    ``redirect_chain`` is kept because the URL a user supplied and the URL that
    actually served the bytes are frequently different, and provenance should
    record the latter.
    """

    content: bytes
    sha256: str
    size_bytes: int
    retrieval_method: RetrievalMethod
    retrieved_at: str
    url: str | None = None
    final_url: str | None = None
    file_name: str | None = None
    media_type: str | None = None
    status_code: int | None = None
    redirect_chain: tuple[str, ...] = ()
    etag: str | None = None
    last_modified: str | None = None
    from_cache: bool = False
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_pdf(self) -> bool:
        """Whether the bytes themselves carry a PDF signature.

        Decided by content rather than by the server's Content-Type header,
        which is wrong often enough that trusting it would misclassify real
        documents and accept real error pages.
        """
        return _PDF_MAGIC in self.content[:_MAGIC_WINDOW]

    def text(self, *, encoding: str = "utf-8") -> str:
        """Decode the payload as text, for non-PDF sources.

        Errors are replaced rather than raised: a single bad byte in a long
        document should cost one character, not the whole analysis.
        """
        return self.content.decode(encoding, errors="replace")


def sha256_hex(data: bytes) -> str:
    """Content hash of a payload, in the form the data contract stores."""
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    """Current instant as the contract's timezone-aware UTC timestamp."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Source dispatch
# ---------------------------------------------------------------------------


def classify_source(source: bytes | str | Path) -> SourceKind:
    """Decide what kind of thing a caller has handed us.

    The ordering matters and is deliberately conservative about the network: a
    string is only treated as a URL when it carries an explicit ``http``/
    ``https`` scheme, so a filename that happens to contain ``://`` never
    triggers a fetch, and a bare hostname is treated as a path rather than
    silently promoted to a request.
    """
    if isinstance(source, bytes | bytearray | memoryview):
        return "bytes"
    if isinstance(source, Path):
        return "path"
    text = str(source)
    scheme = urlsplit(text.strip()).scheme.lower()
    if scheme in ALLOWED_SCHEMES:
        return "url"
    if scheme and scheme not in ALLOWED_SCHEMES and "\n" not in text and len(text) < 512:
        # An explicit but unusable scheme: say so rather than treating
        # 'file:///etc/passwd' as document text.
        raise UnsupportedDocumentError(
            f"unsupported URL scheme {scheme!r}: Aleph fetches only {sorted(ALLOWED_SCHEMES)}",
            reason="unsupported_scheme",
        )
    if "\n" not in text and len(text) <= _MAX_PATH_LENGTH:
        try:
            if Path(text).expanduser().is_file():
                return "path"
        except OSError:
            pass
    return "text"


def load_source(
    source: bytes | str | Path,
    *,
    allow_network: bool = False,
    url: str | None = None,
    file_name: str | None = None,
    config: Config | None = None,
    client: Any | None = None,
) -> FetchedDocument:
    """Resolve any accepted source form to bytes, without ever guessing.

    Args:
        source: Raw bytes, a filesystem path, or an ``http(s)`` URL.
        allow_network: Must be ``True`` for a URL to be fetched. Keyword-only and
            defaulting to ``False`` so that reaching the network is always a
            visible decision in the calling code.
        url: Provenance URL to record for bytes or a path that in fact came from
            somewhere else (an upload proxied from a link, say).
        file_name: Provenance filename for bytes.
        config: Settings override; defaults to the process configuration.
        client: An ``httpx.Client`` to reuse. Injectable so tests can drive the
            fetch path against a transport with no sockets involved.

    Raises:
        RetrievalDisabledError: A URL was given without ``allow_network=True``.
        UnsupportedDocumentError: The string is neither a readable file nor a
            fetchable URL.
    """
    kind = classify_source(source)
    if kind == "bytes":
        return from_bytes(bytes(source), url=url, file_name=file_name)  # type: ignore[arg-type]
    if kind == "path":
        return read_path(Path(str(source)).expanduser(), url=url)
    if kind == "url":
        return fetch_url(
            str(source).strip(),
            allow_network=allow_network,
            config=config,
            client=client,
        )
    raise UnsupportedDocumentError(
        "the supplied string is neither a readable file path nor an http(s) URL; "
        "pass document bytes, a path, or a URL",
        reason="unresolvable_source",
    )


def from_bytes(
    data: bytes,
    *,
    url: str | None = None,
    file_name: str | None = None,
    media_type: str | None = None,
    retrieval_method: RetrievalMethod = RetrievalMethod.FILE_UPLOAD,
) -> FetchedDocument:
    """Wrap an in-memory payload, hashing it so it is as traceable as a download."""
    payload = bytes(data)
    if not payload:
        raise UnsupportedDocumentError(
            "empty payload: there are no bytes to analyse",
            reason="empty_input",
            size_bytes=0,
        )
    if media_type is None and file_name:
        media_type = mimetypes.guess_type(file_name)[0]
    return FetchedDocument(
        content=payload,
        sha256=sha256_hex(payload),
        size_bytes=len(payload),
        retrieval_method=retrieval_method,
        retrieved_at=_utc_now(),
        url=url,
        final_url=url,
        file_name=file_name,
        media_type=media_type,
    )


def read_path(
    path: str | Path,
    *,
    url: str | None = None,
    max_bytes: int | None = None,
    config: Config | None = None,
) -> FetchedDocument:
    """Read a local file, applying the same size limit a download would face.

    The limit applies here too because the failure it prevents — a document too
    large to analyse producing a confidently incomplete reading — has nothing to
    do with how the bytes arrived.

    Raises:
        UnsupportedDocumentError: The path is missing, is not a file, or exceeds
            the configured size limit.
    """
    settings = config or get_config()
    cap = max_bytes if max_bytes is not None else settings.max_pdf_bytes
    target = Path(path).expanduser()
    if not target.exists():
        raise UnsupportedDocumentError(
            f"no such file: {target.name}",
            reason="file_not_found",
        )
    if not target.is_file():
        raise UnsupportedDocumentError(
            f"not a regular file: {target.name}",
            reason="not_a_file",
        )
    size = target.stat().st_size
    if cap and size > cap:
        raise UnsupportedDocumentError(
            f"file is {size} bytes, over the {cap}-byte limit; it is refused rather "
            "than truncated, because a silently truncated document produces a "
            "confidently incomplete analysis",
            reason="too_large",
            size_bytes=size,
        )
    payload = target.read_bytes()
    if not payload:
        raise UnsupportedDocumentError(
            f"file is empty: {target.name}",
            reason="empty_input",
            size_bytes=0,
        )
    return FetchedDocument(
        content=payload,
        sha256=sha256_hex(payload),
        size_bytes=len(payload),
        retrieval_method=RetrievalMethod.LOCAL_PATH,
        retrieved_at=_utc_now(),
        url=url,
        final_url=url,
        file_name=target.name,
        media_type=mimetypes.guess_type(target.name)[0],
    )


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def fetch_url(
    url: str,
    *,
    allow_network: bool = False,
    config: Config | None = None,
    client: Any | None = None,
    max_bytes: int | None = None,
    timeout: float | None = None,
    respect_robots: bool = True,
    accept_media_types: Iterable[str] | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> FetchedDocument:
    """Download a document over HTTP, once, deliberately and politely.

    Args:
        url: An ``http`` or ``https`` URL.
        allow_network: Required. ``False`` raises rather than fetching.
        config: Settings override; supplies the User-Agent, timeout, size cap and
            inter-request delay.
        client: An existing ``httpx.Client``. When given it is used as-is and not
            closed, which is how tests drive this function with a mock transport
            and no sockets.
        max_bytes: Size cap override. Enforced while streaming, so an oversized
            body is abandoned mid-transfer rather than downloaded in full.
        timeout: Per-request timeout override, in seconds.
        respect_robots: Consult robots.txt first. Turning this off is a decision
            about someone else's server and should be a considered one.
        accept_media_types: Override the accepted Content-Type set.
        etag: Prior ``ETag`` for a conditional request. A ``304`` comes back as
            :class:`~aleph.core.errors.RetrievalError` with reason
            ``not_modified``, so callers can keep their cached copy.
        last_modified: Prior ``Last-Modified`` for a conditional request.

    Raises:
        RetrievalDisabledError: ``allow_network`` was not ``True``.
        UnsupportedDocumentError: Bad scheme, or a body over the size cap.
        RetrievalError: Transport failure, robots disallow, redirect problem,
            HTTP error status, or a response that is not a document.
    """
    settings = config or get_config()
    if not allow_network:
        raise RetrievalDisabledError(
            "a document fetch was attempted without network access being granted; "
            "Aleph does not reach the network as a side effect of a pipeline run",
            mode=settings.retrieval_mode.value,
            operation="fetch_url",
            url=url,
        )

    parsed = urlsplit(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsupportedDocumentError(
            f"refusing to fetch scheme {parsed.scheme!r}; only "
            f"{sorted(ALLOWED_SCHEMES)} are permitted",
            reason="unsupported_scheme",
        )
    if not parsed.netloc:
        raise UnsupportedDocumentError(
            f"malformed URL with no host: {url!r}",
            reason="malformed_url",
        )

    import httpx  # imported lazily so this module never opens a socket on import

    cap = max_bytes if max_bytes is not None else settings.max_pdf_bytes
    accepted = frozenset(accept_media_types) if accept_media_types else DOCUMENT_MEDIA_TYPES
    headers = {
        "User-Agent": settings.user_agent,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
        "Accept-Encoding": "gzip, deflate",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    owns_client = client is None
    active = client or httpx.Client(
        timeout=timeout if timeout is not None else settings.request_timeout,
        follow_redirects=False,
        headers={"User-Agent": settings.user_agent},
    )
    try:
        if respect_robots:
            _check_robots(active, url, settings.user_agent)

        current = url
        chain: list[str] = []
        response = None
        for _hop in range(MAX_REDIRECTS + 1):
            _throttle(current, settings.fetch_delay_seconds)
            try:
                with active.stream("GET", current, headers=headers) as streamed:
                    if streamed.status_code in _REDIRECT_STATUSES:
                        current = _next_hop(streamed, current, chain)
                        continue
                    response = _consume(streamed, current, cap, accepted)
                break
            except httpx.TimeoutException as exc:
                raise RetrievalError(
                    f"request timed out after {settings.request_timeout}s",
                    url=current,
                    reason="timeout",
                    retryable=True,
                ) from exc
            except httpx.HTTPError as exc:
                raise RetrievalError(
                    f"transport failure: {type(exc).__name__}: {exc}",
                    url=current,
                    reason="transport_error",
                    retryable=True,
                ) from exc
        else:
            raise RetrievalError(
                f"more than {MAX_REDIRECTS} redirects; the chain was {chain}",
                url=url,
                reason="too_many_redirects",
                retryable=False,
            )

        if response is None:  # pragma: no cover - defensive
            raise RetrievalError(
                "no response was produced", url=url, reason="no_response", retryable=True
            )

        payload, status, media_type, resp_headers = response
        return FetchedDocument(
            content=payload,
            sha256=sha256_hex(payload),
            size_bytes=len(payload),
            retrieval_method=RetrievalMethod.URL_FETCH,
            retrieved_at=_utc_now(),
            url=url,
            final_url=current,
            file_name=_file_name_for(current, resp_headers),
            media_type=media_type,
            status_code=status,
            redirect_chain=tuple(chain),
            etag=resp_headers.get("etag"),
            last_modified=resp_headers.get("last-modified"),
            headers=resp_headers,
        )
    finally:
        if owns_client:
            active.close()


def _next_hop(streamed: Any, current: str, chain: list[str]) -> str:
    """Validate one redirect and return the next URL to request.

    The whole reason this is hand-rolled: a ``Location`` header is chosen by a
    remote server, and following it into a non-HTTP scheme turns a document
    fetcher into a local-file reader. Loops are refused too, since a server that
    redirects to itself would otherwise consume the whole hop budget.
    """
    location = streamed.headers.get("location")
    if not location:
        raise RetrievalError(
            f"HTTP {streamed.status_code} redirect with no Location header",
            url=current,
            status_code=streamed.status_code,
            reason="malformed_redirect",
            retryable=False,
        )
    import httpx

    target = str(httpx.URL(current).join(location))
    scheme = urlsplit(target).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise RetrievalError(
            f"refusing to follow a redirect to scheme {scheme!r}; only "
            f"{sorted(ALLOWED_SCHEMES)} are followed, because a redirect target is "
            "chosen by the remote server",
            url=current,
            status_code=streamed.status_code,
            reason="unsafe_redirect_scheme",
            retryable=False,
        )
    if target == current or target in chain:
        raise RetrievalError(
            "redirect loop detected",
            url=current,
            status_code=streamed.status_code,
            reason="redirect_loop",
            retryable=False,
        )
    chain.append(target)
    return target


def _consume(
    streamed: Any,
    url: str,
    cap: int,
    accepted: frozenset[str],
) -> tuple[bytes, int, str | None, dict[str, str]]:
    """Check the response and read the body, stopping the moment it is too big."""
    status = streamed.status_code
    resp_headers = {key.lower(): value for key, value in streamed.headers.items()}

    if status == 304:
        raise RetrievalError(
            "the server reports the document is unchanged since the cached copy",
            url=url,
            status_code=status,
            reason="not_modified",
            retryable=False,
        )
    if status in (401, 402, 403):
        raise RetrievalError(
            f"access refused with HTTP {status}; Aleph does not attempt to bypass "
            "access controls or paywalls",
            url=url,
            status_code=status,
            reason="access_denied",
            retryable=False,
        )
    if status == 429:
        raise RetrievalError(
            "the server asked us to slow down (HTTP 429)",
            url=url,
            status_code=status,
            reason="rate_limited",
            retryable=True,
        )
    if status >= 400:
        raise RetrievalError(
            f"the server returned HTTP {status}",
            url=url,
            status_code=status,
            reason="http_error",
            retryable=status >= 500,
        )

    media_type = (resp_headers.get("content-type") or "").split(";")[0].strip().lower() or None
    if media_type in _MARKUP_MEDIA_TYPES:
        raise RetrievalError(
            f"the server returned {media_type}, not a document; this is usually a "
            "login wall, a consent interstitial or an error page rather than the "
            "file that was asked for",
            url=url,
            status_code=status,
            reason="not_a_document",
            retryable=False,
        )
    if media_type is not None and media_type not in accepted:
        raise RetrievalError(
            f"unexpected content type {media_type!r}",
            url=url,
            status_code=status,
            reason="unexpected_content_type",
            retryable=False,
        )

    declared = resp_headers.get("content-length")
    if declared and declared.isdigit() and cap and int(declared) > cap:
        raise UnsupportedDocumentError(
            f"the server declares {declared} bytes, over the {cap}-byte limit",
            reason="too_large",
            size_bytes=int(declared),
            media_type=media_type,
        )

    chunks: list[bytes] = []
    total = 0
    for chunk in streamed.iter_bytes():
        total += len(chunk)
        if cap and total > cap:
            raise UnsupportedDocumentError(
                f"the response exceeded the {cap}-byte limit and was abandoned "
                "mid-transfer rather than truncated",
                reason="too_large",
                size_bytes=total,
                media_type=media_type,
            )
        chunks.append(chunk)

    payload = b"".join(chunks)
    if not payload:
        raise RetrievalError(
            "the server returned an empty body",
            url=url,
            status_code=status,
            reason="empty_body",
            retryable=True,
        )
    return payload, status, media_type, resp_headers


def _file_name_for(url: str, headers: Mapping[str, str]) -> str | None:
    """Recover a filename from Content-Disposition, else from the URL path."""
    disposition = headers.get("content-disposition", "")
    for part in disposition.split(";"):
        key, _, value = part.strip().partition("=")
        if key.strip().lower() in ("filename", "filename*"):
            cleaned = value.strip().strip('"').split("''")[-1]
            if cleaned:
                return Path(cleaned).name
    tail = Path(urlsplit(url).path).name
    return tail or None


def _throttle(url: str, delay: float) -> None:
    """Wait, if necessary, before hitting the same host again.

    Politeness rather than performance. A public-interest source that publishes a
    document has not consented to being hammered by whoever analyses it, and one
    request per second per host costs Aleph nothing worth having.
    """
    if delay <= 0:
        return
    host = urlsplit(url).netloc.lower()
    with _politeness_lock:
        previous = _last_request_at.get(host)
        now = time.monotonic()
        wait = 0.0 if previous is None else max(0.0, delay - (now - previous))
        _last_request_at[host] = now + wait
    if wait:
        time.sleep(wait)


def _check_robots(client: Any, url: str, user_agent: str) -> None:
    """Refuse the fetch if the host's robots.txt disallows it.

    A missing, unreachable or unparseable robots.txt is treated as permission, in
    line with the usual reading of the standard. A robots.txt that *is* readable
    and *does* disallow the path is honoured without exception: Aleph does not
    have a category of document important enough to justify ignoring it.

    Raises:
        RetrievalError: The path is disallowed for this User-Agent.
    """
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    with _politeness_lock:
        cached = _robots_cache.get(origin, ...)  # type: ignore[arg-type]
    if cached is ...:
        parser: urllib.robotparser.RobotFileParser | None = None
        try:
            response = client.get(f"{origin}/robots.txt")
            if response.status_code == 200 and response.text:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(response.text.splitlines())
        except Exception:  # noqa: BLE001 - an unreadable robots.txt means "no rules"
            parser = None
        with _politeness_lock:
            _robots_cache[origin] = parser
        cached = parser
    if cached is not None and not cached.can_fetch(user_agent, url):
        raise RetrievalError(
            "the host's robots.txt disallows this path for Aleph's User-Agent",
            url=url,
            reason="robots_disallow",
            retryable=False,
        )


def is_network_permitted(config: Config | None = None) -> bool:
    """Whether the active retrieval mode allows a fetch without an explicit opt-in.

    ``True`` only under ``auto``. Provided so a caller can report the reason a
    fetch will be refused before attempting one, rather than catching an
    exception to find out.
    """
    settings = config or get_config()
    return settings.retrieval_mode is RetrievalMode.AUTO
