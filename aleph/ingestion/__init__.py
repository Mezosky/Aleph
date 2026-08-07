"""Getting a document's bytes and turning them into citable text.

Three modules, and the order they run in is the order they appear here:

* :mod:`aleph.ingestion.fetch` — resolves bytes, a path or a URL to one
  :class:`~aleph.ingestion.fetch.FetchedDocument` with a content hash. Network
  access requires an explicit ``allow_network=True``; without it the fetch raises
  rather than quietly emitting traffic, so a pipeline run can never reach a
  stranger's server as a side effect and can never have its evidence base shift
  underneath it mid-analysis.
* :mod:`aleph.ingestion.pdf` — extracts text *with* page numbers, character
  offsets and per-block typography, and reports honestly when a file turned out
  to be a scan. A document that could not be read must never look like a document
  that says nothing.
* :mod:`aleph.ingestion.normalize` — repairs hyphenation, ligatures, exotic
  spaces and repeated running headers while recording an offset map back to the
  untouched extraction, so cleaned text stays quotable and every span stays
  auditable.

The through-line is that no stage here is allowed to trade traceability for
convenience. Text that cannot be pointed back at a page is text Aleph cannot
publish a verdict on, so the located structure survives every transformation
rather than being discarded once it has served its purpose.

Nothing in this package knows what jurisdiction, language or kind of document it
is handling, and nothing performs I/O at import time.
"""

from __future__ import annotations

from aleph.ingestion.fetch import (
    ALLOWED_SCHEMES,
    DOCUMENT_MEDIA_TYPES,
    FetchedDocument,
    classify_source,
    fetch_url,
    from_bytes,
    is_network_permitted,
    load_source,
    read_path,
    sha256_hex,
)
from aleph.ingestion.normalize import (
    NORMALIZER_VERSION,
    NormalizedDocument,
    NormalizedPage,
    NormalizeOptions,
    OffsetMap,
    fold_accents,
    normalize_document,
    normalize_text,
)
from aleph.ingestion.pdf import (
    EXTRACTOR_VERSION,
    PAGE_SEPARATOR,
    BoundingBox,
    ExtractedDocument,
    ExtractedPage,
    StyleRange,
    TextBlock,
    extract_pdf,
    extract_plain_text,
    extract_with_pymupdf,
    extract_with_pypdf,
    looks_like_pdf,
)

__all__ = [
    # fetch
    "ALLOWED_SCHEMES",
    "DOCUMENT_MEDIA_TYPES",
    "FetchedDocument",
    "classify_source",
    "fetch_url",
    "from_bytes",
    "is_network_permitted",
    "load_source",
    "read_path",
    "sha256_hex",
    # pdf
    "EXTRACTOR_VERSION",
    "PAGE_SEPARATOR",
    "BoundingBox",
    "ExtractedDocument",
    "ExtractedPage",
    "StyleRange",
    "TextBlock",
    "extract_pdf",
    "extract_plain_text",
    "extract_with_pymupdf",
    "extract_with_pypdf",
    "looks_like_pdf",
    # normalize
    "NORMALIZER_VERSION",
    "NormalizeOptions",
    "NormalizedDocument",
    "NormalizedPage",
    "OffsetMap",
    "fold_accents",
    "normalize_document",
    "normalize_text",
]
