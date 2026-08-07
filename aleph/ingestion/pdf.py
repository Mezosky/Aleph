"""Turning a PDF's bytes into text that can still be pointed at.

Text extraction is the point at which Aleph's whole traceability guarantee is
either established or quietly lost. Every later claim — a provision, a
proposition, a verdict — is required to carry a verbatim span, and a span is only
meaningful if the extractor recorded *where* the characters came from. So this
module never returns a bare string. It returns pages with character offsets,
and blocks with font size, weight and bounding box, because those are what let
:mod:`aleph.documents.sections` recover a document's outline and what let a
reader be shown the passage an assertion rests on.

Two failure modes are treated as first-class results rather than as noise.

**The silently empty page.** A scanned instrument yields a PDF with no text
layer. Naive extraction returns ``""``, which flows downstream as a document with
no provisions, which becomes an analysis with nothing to say — and "the document
contains no obligations" is a very different statement from "we could not read
the document". :func:`extract_pdf` counts pages that carry images but no text and
raises the result to an explicit ``scanned_images_only`` warning with an
``ExtractionQuality`` state of ``poor``, so downstream confidence is capped by
what was actually legible.

**The degraded fallback.** When PyMuPDF is unavailable or fails, pypdf still
recovers text but no typography. Heading detection then has only numbering to
work from, and the resulting outline is weaker. That is recorded as a warning
rather than absorbed, because an outline built from a guess should be labelled as
one.

Nothing here is jurisdiction-aware: this module sees glyphs, boxes and offsets,
and has no opinion about what kind of document it is reading.
"""

from __future__ import annotations

import io
import re
import statistics
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from aleph.core.enums import (
    ExtractionMethod,
    ExtractionQualityState,
    ExtractionWarningCode,
    WarningSeverity,
)
from aleph.core.errors import DocumentParseError, UnsupportedDocumentError
from aleph.core.models import ExtractionQuality, ExtractionWarning

__all__ = [
    "PAGE_SEPARATOR",
    "PDF_MAGIC",
    "EXTRACTOR_VERSION",
    "BoundingBox",
    "TextBlock",
    "ExtractedPage",
    "ExtractedDocument",
    "StyleRange",
    "looks_like_pdf",
    "extract_pdf",
    "extract_with_pymupdf",
    "extract_with_pypdf",
    "extract_plain_text",
]

#: Inserted between pages when page texts are concatenated into one string.
#: Two newlines, so a page break also reads as a paragraph break and no sentence
#: is accidentally welded to the first line of the following page.
PAGE_SEPARATOR: Final[str] = "\n\n"

#: The PDF file signature. Searched for near the start rather than required at
#: offset 0, because real-world files routinely carry a few junk bytes ahead of it.
PDF_MAGIC: Final[bytes] = b"%PDF-"

#: Version of this extractor. Recorded on every document so that a span produced
#: by an older extractor can be invalidated rather than silently trusted.
EXTRACTOR_VERSION: Final[str] = "aleph.ingestion.pdf/1.0.0"

#: How far into the file the signature may appear.
_MAGIC_SEARCH_WINDOW: Final[int] = 2048

#: A page with fewer than this many non-space characters is treated as carrying
#: no usable text. Deliberately low: a page holding only a heading is still a
#: page Aleph read, and calling it unreadable would understate coverage.
MIN_CHARS_FOR_TEXT_PAGE: Final[int] = 24

#: Fraction of image-bearing, text-free pages above which the whole document is
#: reported as scanned rather than as merely sparse.
SCANNED_PAGE_RATIO: Final[float] = 0.6

#: Average characters per page above which extraction is considered dense enough
#: to call ``good`` rather than ``degraded``.
_DENSE_PAGE_CHARS: Final[int] = 200

#: PyMuPDF span flag bit for a bold face.
_MUPDF_BOLD_FLAG: Final[int] = 1 << 4

#: Substrings in a PostScript font name that indicate weight. Checked because a
#: great many PDFs embed a bold face without setting the bold flag.
_BOLD_NAME_HINTS: Final[tuple[str, ...]] = (
    "bold",
    "black",
    "heavy",
    "semibold",
    "demibold",
    "extrabold",
    "ultrabold",
)

#: Upper bound on pages for which table detection is attempted. Table finding is
#: superlinear on pathological files and is a diagnostic, not a requirement.
_TABLE_DETECTION_PAGE_LIMIT: Final[int] = 300

_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Structured extraction result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Position of a block on its page, in PDF points, origin top-left.

    Kept because vertical position is evidence about role: a line at the very top
    or bottom of every page is a running header, not a heading, and
    :mod:`aleph.ingestion.normalize` needs to be able to tell those apart.
    """

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True, slots=True)
class TextBlock:
    """One typographic block of a page, with the style information intact.

    ``font_size`` and ``is_bold`` are the raw material of heading detection. They
    are ``None``/``False`` when the extraction path could not recover them, and
    that absence is reported as a warning rather than defaulted to a plausible
    number: a fabricated font size would produce a fabricated outline.

    ``char_start`` and ``char_end`` are offsets into the *page's* text, so a
    block can be located without reference to the rest of the document.
    """

    text: str
    page: int
    char_start: int
    char_end: int
    font_size: float | None = None
    is_bold: bool = False
    font_name: str | None = None
    bbox: BoundingBox | None = None
    line_count: int = 1


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    """One page of extracted text, locatable in the whole-document string.

    ``char_start``/``char_end`` index the concatenated document text; block
    offsets index this page's text. Both are kept so that a span can be reported
    the way the data contract asks for it — page number plus page-relative
    offsets — while text processing can still run over the document as a whole.
    """

    page_number: int
    text: str
    char_start: int
    char_end: int
    blocks: tuple[TextBlock, ...] = ()
    width: float | None = None
    height: float | None = None
    image_count: int = 0
    table_count: int = 0

    @property
    def char_count(self) -> int:
        """Non-whitespace characters recovered from this page."""
        return len(self.text.strip())

    @property
    def has_text(self) -> bool:
        """Whether this page yielded enough text to be worth analysing."""
        return self.char_count >= MIN_CHARS_FOR_TEXT_PAGE

    @property
    def is_image_only(self) -> bool:
        """Whether this page appears to be a picture of text rather than text.

        The distinguishing signal is an image present *and* no text layer. A page
        that is genuinely blank has neither and is not evidence of a scan.
        """
        return self.image_count > 0 and not self.has_text


@dataclass(frozen=True, slots=True)
class StyleRange:
    """A document-level character range and the typography that covers it.

    Emitted by :meth:`ExtractedDocument.style_ranges` so that
    :mod:`aleph.documents.sections` can consult typography without importing this
    module's page and block types — heading detection must remain usable on a
    plain-text fixture that has no typography at all.
    """

    char_start: int
    char_end: int
    font_size: float | None
    is_bold: bool
    page: int


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    """The complete, located result of reading one file.

    ``text`` is the concatenation of page texts joined by :data:`PAGE_SEPARATOR`;
    every page and every block can be mapped back into it. ``quality`` and
    ``warnings`` travel with the text rather than beside it, because the single
    most damaging thing an extractor can do is hand downstream code a short
    string with no indication that most of the document was unreadable.
    """

    text: str
    pages: tuple[ExtractedPage, ...]
    extraction_method: ExtractionMethod
    quality: ExtractionQuality
    warnings: tuple[ExtractionWarning, ...] = ()
    is_scanned: bool = False
    is_encrypted: bool = False
    metadata: dict[str, str] = field(default_factory=dict)
    extractor_version: str = EXTRACTOR_VERSION

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def quality_score(self) -> float:
        """A single [0,1] figure for how well extraction went.

        The product of two things a reader would want to know separately but a
        caller often needs as one number: how many pages produced text at all,
        and how dense that text was relative to a normally-typeset page. It is a
        *cap* on downstream confidence, never a substitute for
        :attr:`quality`, which says what specifically went wrong.
        """
        if not self.pages:
            return 0.0
        coverage = sum(1 for page in self.pages if page.has_text) / len(self.pages)
        density = min(1.0, (self.char_count / len(self.pages)) / _DENSE_PAGE_CHARS)
        return round(coverage * (0.5 + 0.5 * density), 4)

    @property
    def has_layout(self) -> bool:
        """Whether any block carries a font size.

        ``False`` means heading detection has only numbering to work with, and
        the resulting outline should be treated as weaker.
        """
        return any(block.font_size is not None for page in self.pages for block in page.blocks)

    def page_at(self, offset: int) -> ExtractedPage | None:
        """Return the page containing a document-level character offset.

        Offsets that land in the separator between two pages are attributed to
        the earlier page, so that a span never silently loses its page number.
        """
        found: ExtractedPage | None = None
        for page in self.pages:
            if page.char_start <= offset:
                found = page
            else:
                break
        return found

    def page_ranges(self) -> tuple[tuple[int, int], ...]:
        """Document-level ``(start, end)`` offsets of every page, in order."""
        return tuple((page.char_start, page.char_end) for page in self.pages)

    def style_ranges(self) -> Iterator[StyleRange]:
        """Yield every block as a document-level range plus its typography."""
        for page in self.pages:
            for block in page.blocks:
                yield StyleRange(
                    char_start=page.char_start + block.char_start,
                    char_end=page.char_start + block.char_end,
                    font_size=block.font_size,
                    is_bold=block.is_bold,
                    page=page.page_number,
                )

    def body_font_size(self) -> float | None:
        """The font size covering the most characters, i.e. the body text size.

        Returned as the baseline against which a heading is "large". Computed by
        character weight rather than by block count so that a document with many
        short captions does not report caption size as its body size.
        """
        weights: dict[float, int] = {}
        for page in self.pages:
            for block in page.blocks:
                if block.font_size is None:
                    continue
                key = round(block.font_size, 1)
                weights[key] = weights.get(key, 0) + max(1, len(block.text))
        if not weights:
            return None
        return max(weights.items(), key=lambda item: (item[1], -item[0]))[0]


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def looks_like_pdf(data: bytes) -> bool:
    """Whether these bytes carry a PDF signature near their start.

    Checked by content rather than by filename or declared media type: a server
    that labels a PDF ``application/octet-stream`` is common, and an HTML error
    page served as ``application/pdf`` is commoner still.
    """
    return PDF_MAGIC in data[:_MAGIC_SEARCH_WINDOW]


def extract_pdf(
    data: bytes,
    *,
    password: str | None = None,
    prefer: ExtractionMethod | None = None,
    detect_tables: bool = True,
    source_name: str | None = None,
) -> ExtractedDocument:
    """Extract located text from PDF bytes, with layout where it is available.

    PyMuPDF is tried first because it is the only one of the two backends that
    recovers font size, weight and geometry, and without those the document
    outline degrades to whatever numbering the text happens to carry. pypdf is
    the fallback; when it is used, the loss of typography is recorded as a
    warning rather than passed on silently.

    Args:
        data: The raw file bytes.
        password: Password for an encrypted file. An empty-password file is
            opened without one.
        prefer: Force a backend. Mainly for tests and for reproducing a result
            recorded under a specific ``extraction_method``.
        detect_tables: Whether to count tables per page. Diagnostic only;
            disabled automatically for very long documents.
        source_name: Human-readable origin, used only in error messages.

    Returns:
        An :class:`ExtractedDocument` whose ``quality`` and ``warnings`` describe
        honestly how much of the file was actually read.

    Raises:
        UnsupportedDocumentError: The bytes are not a PDF, or the file is
            encrypted and the password did not open it. Terminal: no retry and no
            other backend will help.
        DocumentParseError: Both backends failed on a file that is a PDF.
    """
    if not data:
        raise UnsupportedDocumentError(
            "empty input: there are no bytes to extract text from",
            reason="empty_input",
            size_bytes=0,
        )
    if not looks_like_pdf(data):
        raise UnsupportedDocumentError(
            f"input does not carry a PDF signature in its first {_MAGIC_SEARCH_WINDOW} bytes",
            reason="not_a_pdf",
            detected=_sniff(data),
            size_bytes=len(data),
        )

    order: tuple[ExtractionMethod, ...]
    if prefer is ExtractionMethod.PYPDF_TEXT:
        order = (ExtractionMethod.PYPDF_TEXT,)
    elif prefer is ExtractionMethod.PYMUPDF_TEXT:
        order = (ExtractionMethod.PYMUPDF_TEXT,)
    else:
        order = (ExtractionMethod.PYMUPDF_TEXT, ExtractionMethod.PYPDF_TEXT)

    failures: list[str] = []
    for method in order:
        try:
            if method is ExtractionMethod.PYMUPDF_TEXT:
                return extract_with_pymupdf(data, password=password, detect_tables=detect_tables)
            return extract_with_pypdf(data, password=password)
        except UnsupportedDocumentError:
            raise
        except Exception as exc:  # noqa: BLE001 - backend failures are diverse by nature
            failures.append(f"{method.value}: {type(exc).__name__}: {exc}")

    raise DocumentParseError(
        "no PDF backend could read this file",
        source=source_name,
        stage="text_extraction",
        recoverable=False,
        attempts=failures,
    )


def extract_with_pymupdf(
    data: bytes,
    *,
    password: str | None = None,
    detect_tables: bool = True,
) -> ExtractedDocument:
    """Extract text, geometry and typography with PyMuPDF.

    Page text is rebuilt from the block structure rather than taken from a
    separate flat-text call, so that every recorded block offset indexes the
    exact string that is returned. Two extractions that disagree about where a
    block starts would make every downstream span subtly wrong.

    Raises:
        UnsupportedDocumentError: The file is encrypted and could not be opened.
    """
    import pymupdf  # imported here so the module stays importable without it

    warnings: list[ExtractionWarning] = []
    is_encrypted = False

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if doc.needs_pass:
            is_encrypted = True
            if not doc.authenticate(password or ""):
                raise UnsupportedDocumentError(
                    "the file is encrypted and the supplied password did not open it",
                    reason="encrypted",
                    media_type="application/pdf",
                    size_bytes=len(data),
                )
            warnings.append(
                ExtractionWarning(
                    code=ExtractionWarningCode.ENCRYPTED_FILE,
                    severity=WarningSeverity.INFO,
                    message=(
                        "the file was encrypted and was opened with the supplied "
                        "password; permissions set by the author may still restrict "
                        "what could be extracted"
                    ),
                )
            )

        metadata = {
            key: str(value)
            for key, value in (doc.metadata or {}).items()
            if value not in (None, "")
        }
        page_count = doc.page_count
        want_tables = detect_tables and page_count <= _TABLE_DETECTION_PAGE_LIMIT

        pages: list[ExtractedPage] = []
        cursor = 0
        for index in range(page_count):
            page = doc.load_page(index)
            page_number = index + 1
            try:
                raw = page.get_text("dict", sort=True)
            except TypeError:  # older bindings without ``sort``
                raw = page.get_text("dict")
            except Exception as exc:  # noqa: BLE001 - one bad page must not lose the rest
                warnings.append(
                    ExtractionWarning(
                        code=ExtractionWarningCode.MISSING_PAGES,
                        severity=WarningSeverity.WARNING,
                        message=f"page {page_number} could not be decoded: {exc}",
                        page=page_number,
                    )
                )
                raw = {"blocks": [], "width": None, "height": None}

            page_text, blocks = _blocks_from_mupdf(raw.get("blocks", ()), page_number)

            try:
                image_count = len(page.get_images(full=True))
            except Exception:  # noqa: BLE001 - image listing is diagnostic only
                image_count = 0

            table_count = 0
            if want_tables:
                try:
                    table_count = len(page.find_tables().tables)
                except Exception:  # noqa: BLE001 - table finding is best-effort
                    table_count = 0

            # The separator is inserted between every pair of pages, including
            # when a page is empty, because ``_assemble`` joins unconditionally.
            # Keying this off the index rather than off ``cursor`` matters: a
            # leading blank page would otherwise desynchronise every offset that
            # follows it.
            if index > 0:
                cursor += len(PAGE_SEPARATOR)

            pages.append(
                ExtractedPage(
                    page_number=page_number,
                    text=page_text,
                    char_start=cursor,
                    char_end=cursor + len(page_text),
                    blocks=blocks,
                    width=_as_float(raw.get("width")),
                    height=_as_float(raw.get("height")),
                    image_count=image_count,
                    table_count=table_count,
                )
            )
            cursor += len(page_text)

    return _assemble(
        pages,
        method=ExtractionMethod.PYMUPDF_TEXT,
        warnings=warnings,
        metadata=metadata,
        is_encrypted=is_encrypted,
    )


def extract_with_pypdf(data: bytes, *, password: str | None = None) -> ExtractedDocument:
    """Extract text with pypdf, the fallback path.

    pypdf recovers characters but not typography, so the blocks returned here
    carry no font size and no weight. That is reported as a
    ``section_heuristic_fallback`` warning: an outline built without typography
    rests entirely on whatever numbering the document happens to use, and a
    reader is entitled to know that.

    Raises:
        UnsupportedDocumentError: The file is encrypted and could not be opened.
    """
    import pypdf

    warnings: list[ExtractionWarning] = []
    reader = pypdf.PdfReader(io.BytesIO(data))
    is_encrypted = bool(getattr(reader, "is_encrypted", False))
    if is_encrypted:
        try:
            opened = bool(reader.decrypt(password or ""))
        except Exception as exc:  # noqa: BLE001 - pypdf raises several unrelated types
            raise UnsupportedDocumentError(
                f"the file is encrypted and could not be decrypted: {exc}",
                reason="encrypted",
                media_type="application/pdf",
                size_bytes=len(data),
            ) from exc
        if not opened:
            raise UnsupportedDocumentError(
                "the file is encrypted and the supplied password did not open it",
                reason="encrypted",
                media_type="application/pdf",
                size_bytes=len(data),
            )
        warnings.append(
            ExtractionWarning(
                code=ExtractionWarningCode.ENCRYPTED_FILE,
                severity=WarningSeverity.INFO,
                message="the file was encrypted and was opened with the supplied password",
            )
        )

    metadata: dict[str, str] = {}
    try:
        raw_meta = reader.metadata or {}
        metadata = {
            str(key).lstrip("/").lower(): str(value)
            for key, value in raw_meta.items()
            if value not in (None, "")
        }
    except Exception:  # noqa: BLE001 - malformed metadata must not stop extraction
        metadata = {}

    pages: list[ExtractedPage] = []
    cursor = 0
    for index, page in enumerate(reader.pages):
        page_number = index + 1
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - keep the other pages
            warnings.append(
                ExtractionWarning(
                    code=ExtractionWarningCode.MISSING_PAGES,
                    severity=WarningSeverity.WARNING,
                    message=f"page {page_number} could not be decoded: {exc}",
                    page=page_number,
                )
            )
            page_text = ""

        page_text = _TRAILING_WS_RE.sub("", page_text).strip("\n")
        blocks = _blocks_from_plain_text(page_text, page_number)

        try:
            image_count = len(list(getattr(page, "images", ()) or ()))
        except Exception:  # noqa: BLE001 - image listing is diagnostic only
            image_count = 0

        width = height = None
        try:
            box = page.mediabox
            width = float(box.width)
            height = float(box.height)
        except Exception:  # noqa: BLE001 - geometry is diagnostic only
            pass

        if index > 0:
            cursor += len(PAGE_SEPARATOR)
        pages.append(
            ExtractedPage(
                page_number=page_number,
                text=page_text,
                char_start=cursor,
                char_end=cursor + len(page_text),
                blocks=blocks,
                width=width,
                height=height,
                image_count=image_count,
            )
        )
        cursor += len(page_text)

    warnings.append(
        ExtractionWarning(
            code=ExtractionWarningCode.SECTION_HEURISTIC_FALLBACK,
            severity=WarningSeverity.INFO,
            message=(
                "text was extracted without layout information (pypdf backend), so "
                "heading detection can rely only on numbering and line shape; the "
                "resulting outline is weaker than one built from typography"
            ),
            affected_field="structure.sections",
        )
    )

    return _assemble(
        pages,
        method=ExtractionMethod.PYPDF_TEXT,
        warnings=warnings,
        metadata=metadata,
        is_encrypted=is_encrypted,
    )


def extract_plain_text(
    text: str,
    *,
    page_separator: str = "\f",
    method: ExtractionMethod = ExtractionMethod.PLAIN_TEXT,
) -> ExtractedDocument:
    """Wrap an already-decoded string in the same located structure.

    Exists so that every stage after this one can be exercised on a small text
    fixture with no PDF at all. A test that has to build a PDF to check a
    numbering heuristic tests the PDF library, not the heuristic.

    Args:
        text: The document text. Form feeds (or ``page_separator``) mark pages.
        page_separator: Character sequence that starts a new page.
        method: Recorded extraction method; ``fixture`` is appropriate for
            synthetic test material so that it is never mistaken for a reading of
            a real file.
    """
    raw_pages = text.split(page_separator) if page_separator else [text]
    if not raw_pages:
        raw_pages = [""]

    pages: list[ExtractedPage] = []
    cursor = 0
    for index, raw in enumerate(raw_pages):
        page_number = index + 1
        page_text = _TRAILING_WS_RE.sub("", raw).strip("\n")
        if index > 0:
            cursor += len(PAGE_SEPARATOR)
        pages.append(
            ExtractedPage(
                page_number=page_number,
                text=page_text,
                char_start=cursor,
                char_end=cursor + len(page_text),
                blocks=_blocks_from_plain_text(page_text, page_number),
            )
        )
        cursor += len(page_text)

    return _assemble(pages, method=method, warnings=[], metadata={}, is_encrypted=False)


# ---------------------------------------------------------------------------
# Block construction
# ---------------------------------------------------------------------------


def _blocks_from_mupdf(
    raw_blocks: Sequence[Any],
    page_number: int,
) -> tuple[str, tuple[TextBlock, ...]]:
    """Rebuild a page's text from PyMuPDF blocks, keeping style and offsets aligned.

    The returned string is authoritative: block offsets index it exactly. Empty
    blocks are dropped rather than emitted as zero-length ranges, because a
    zero-length block would make ``style_at`` ambiguous at that offset.
    """
    parts: list[str] = []
    blocks: list[TextBlock] = []
    cursor = 0

    for raw in raw_blocks:
        if not isinstance(raw, dict) or raw.get("type") != 0:
            continue  # image or unknown block type: no characters to place
        lines: list[str] = []
        size_weights: dict[float, int] = {}
        bold_chars = 0
        total_chars = 0
        font_names: dict[str, int] = {}

        for line in raw.get("lines", ()):
            chunks: list[str] = []
            for span in line.get("spans", ()):
                span_text = span.get("text", "")
                if not span_text:
                    continue
                chunks.append(span_text)
                length = len(span_text)
                total_chars += length
                size = _as_float(span.get("size"))
                if size is not None:
                    key = round(size, 1)
                    size_weights[key] = size_weights.get(key, 0) + length
                name = span.get("font")
                if name:
                    font_names[str(name)] = font_names.get(str(name), 0) + length
                if _span_is_bold(span):
                    bold_chars += length
            joined = "".join(chunks).rstrip()
            if joined:
                lines.append(joined)

        block_text = "\n".join(lines)
        if not block_text.strip():
            continue

        if parts:
            cursor += len(PAGE_SEPARATOR)
            parts.append(PAGE_SEPARATOR)
        parts.append(block_text)

        font_size = (
            max(size_weights.items(), key=lambda item: (item[1], item[0]))[0]
            if size_weights
            else None
        )
        font_name = (
            max(font_names.items(), key=lambda item: (item[1], item[0]))[0] if font_names else None
        )
        blocks.append(
            TextBlock(
                text=block_text,
                page=page_number,
                char_start=cursor,
                char_end=cursor + len(block_text),
                font_size=font_size,
                is_bold=total_chars > 0 and bold_chars * 2 >= total_chars,
                font_name=font_name,
                bbox=_bbox(raw.get("bbox")),
                line_count=len(lines),
            )
        )
        cursor += len(block_text)

    return "".join(parts), tuple(blocks)


def _blocks_from_plain_text(text: str, page_number: int) -> tuple[TextBlock, ...]:
    """Split flat page text into paragraph blocks with no style information.

    ``font_size`` stays ``None`` and ``is_bold`` stays ``False`` on purpose. A
    default font size would be indistinguishable from a measured one downstream,
    and heading detection would then treat a guess as evidence.
    """
    if not text:
        return ()
    blocks: list[TextBlock] = []
    cursor = 0
    for chunk in _BLANK_LINE_RE.split(text):
        length = len(chunk)
        if chunk.strip():
            blocks.append(
                TextBlock(
                    text=chunk,
                    page=page_number,
                    char_start=cursor,
                    char_end=cursor + length,
                    line_count=chunk.count("\n") + 1,
                )
            )
        # The split consumed a separator; find the real next offset by scanning.
        cursor += length
        match = _BLANK_LINE_RE.match(text, cursor)
        if match:
            cursor = match.end()
    return tuple(blocks)


def _span_is_bold(span: dict[str, Any]) -> bool:
    """Whether a PyMuPDF span is bold, by flag or by embedded font name."""
    flags = span.get("flags")
    if isinstance(flags, int) and flags & _MUPDF_BOLD_FLAG:
        return True
    name = str(span.get("font", "")).lower()
    return any(hint in name for hint in _BOLD_NAME_HINTS)


def _bbox(raw: Any) -> BoundingBox | None:
    if not isinstance(raw, (list, tuple)) or len(raw) < 4:
        return None
    try:
        return BoundingBox(float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Quality assessment
# ---------------------------------------------------------------------------


def _assemble(
    pages: Sequence[ExtractedPage],
    *,
    method: ExtractionMethod,
    warnings: list[ExtractionWarning],
    metadata: dict[str, str],
    is_encrypted: bool,
) -> ExtractedDocument:
    """Join pages into one document and assess honestly how well it went."""
    text = PAGE_SEPARATOR.join(page.text for page in pages)
    quality, extra, is_scanned = _assess_quality(pages, method=method)
    return ExtractedDocument(
        text=text,
        pages=tuple(pages),
        extraction_method=method,
        quality=quality,
        warnings=(*warnings, *extra),
        is_scanned=is_scanned,
        is_encrypted=is_encrypted,
        metadata=metadata,
    )


def _assess_quality(
    pages: Sequence[ExtractedPage],
    *,
    method: ExtractionMethod,
) -> tuple[ExtractionQuality, list[ExtractionWarning], bool]:
    """Measure extraction coverage and decide what to warn about.

    The rule this encodes: an extractor may not report success it did not have.
    ``text_coverage`` is the fraction of pages that produced usable text, and it
    is published so downstream confidence can be capped by it — a verdict resting
    on a document of which two thirds was unreadable is not a verdict.
    """
    warnings: list[ExtractionWarning] = []
    page_count = len(pages)
    if page_count == 0:
        return (
            ExtractionQuality(
                state=ExtractionQualityState.POOR,
                text_coverage=0.0,
                chars_extracted=0,
                note="the file contained no pages",
            ),
            [
                ExtractionWarning(
                    code=ExtractionWarningCode.TRUNCATED_TEXT,
                    severity=WarningSeverity.ERROR,
                    message="no pages were found in the file",
                )
            ],
            False,
        )

    with_text = [page for page in pages if page.has_text]
    without_text = [page.page_number for page in pages if not page.has_text]
    image_only = [page.page_number for page in pages if page.is_image_only]
    chars = sum(page.char_count for page in pages)
    coverage = len(with_text) / page_count
    mean_chars = statistics.fmean(page.char_count for page in pages)
    tables = sum(page.table_count for page in pages)

    is_scanned = bool(image_only) and (len(image_only) / page_count) >= SCANNED_PAGE_RATIO
    if not with_text and any(page.image_count for page in pages):
        is_scanned = True

    if is_scanned:
        state = ExtractionQualityState.POOR
        warnings.append(
            ExtractionWarning(
                code=ExtractionWarningCode.SCANNED_IMAGES_ONLY,
                severity=WarningSeverity.ERROR,
                message=(
                    f"{len(image_only)} of {page_count} pages carry images but no text "
                    "layer: this file appears to be a scan. No OCR was performed, so "
                    "the absence of provisions below reflects what could be read, not "
                    "what the document contains"
                ),
                affected_field="provisions",
            )
        )
    elif coverage >= 0.95 and mean_chars >= _DENSE_PAGE_CHARS:
        state = ExtractionQualityState.GOOD
    elif coverage >= 0.6:
        state = ExtractionQualityState.DEGRADED
    elif coverage > 0.0:
        state = ExtractionQualityState.POOR
    else:
        state = ExtractionQualityState.POOR

    if without_text and not is_scanned:
        warnings.append(
            ExtractionWarning(
                code=ExtractionWarningCode.MISSING_PAGES,
                severity=(WarningSeverity.WARNING if coverage < 0.9 else WarningSeverity.INFO),
                message=(
                    f"{len(without_text)} of {page_count} pages produced no usable text "
                    f"(pages {_compact(without_text)}); anything they contain is absent "
                    "from this analysis"
                ),
                affected_field="provisions",
            )
        )
    if state in (ExtractionQualityState.DEGRADED, ExtractionQualityState.POOR) and not is_scanned:
        warnings.append(
            ExtractionWarning(
                code=ExtractionWarningCode.LOW_TEXT_QUALITY,
                severity=WarningSeverity.WARNING,
                message=(
                    f"text coverage is {coverage:.0%} at a mean of {mean_chars:.0f} "
                    "characters per page; downstream confidence should be capped by this"
                ),
            )
        )

    quality = ExtractionQuality(
        state=state,
        text_coverage=round(coverage, 4),
        chars_extracted=chars,
        pages_without_text=without_text,
        ocr_used=False,
        tables_detected=tables or None,
        note=(f"extracted with {method.value}; {len(with_text)}/{page_count} pages carried text"),
    )
    return quality, warnings, is_scanned


def _compact(numbers: Sequence[int], *, limit: int = 12) -> str:
    """Render a page-number list compactly for a human-readable warning."""
    shown = ", ".join(str(number) for number in numbers[:limit])
    if len(numbers) > limit:
        return f"{shown}, ... (+{len(numbers) - limit} more)"
    return shown


def _sniff(data: bytes) -> str:
    """Best-effort description of what non-PDF bytes actually look like.

    Reported in the refusal so a user learns that their URL returned an HTML
    error page, rather than being told only that the PDF was invalid.
    """
    head = data[:512].lstrip()
    lowered = head[:64].lower()
    if lowered.startswith((b"<!doctype html", b"<html", b"<?xml")):
        return "markup (html/xml)"
    if head.startswith(b"PK\x03\x04"):
        return "zip container (docx/xlsx/odt?)"
    if head.startswith(b"%!PS"):
        return "postscript"
    if head.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8")):
        return "raster image"
    if head.startswith(b"{") or head.startswith(b"["):
        return "json"
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return "binary of unknown type"
    return "plain text"
