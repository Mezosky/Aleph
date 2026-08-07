"""Repairing what PDF extraction breaks, without losing the ability to point back.

Extracted PDF text is not what the document says. Words are cut in half by
line-wrapping hyphens, ligatures arrive as single exotic codepoints, quotation
marks come in four incompatible flavours, non-breaking spaces masquerade as
spaces, and the same running header sits at the top of every one of eighty pages
waiting to be mistaken for a heading. Analysis performed on that raw string finds
``efi ciency`` where the document said ``efficiency`` and reports the publisher's
footer as a provision.

Repairing it is easy. Repairing it *and still being able to say where a phrase
came from* is the part that matters, and it is why this module exists as
something more than a chain of ``str.replace`` calls.

Every transformation here is recorded in an :class:`OffsetMap`, so any offset in
the cleaned text can be translated back to the exact region of the original
extraction it came from. That is what keeps Aleph's central promise honest: a
provision quoted in an analysis can be traced to a character range on a page of
the source file, and a reader who suspects a misquote can check. A normaliser
that dropped the mapping would force a choice between text that is analysable and
text that is citable, and Aleph needs both at once.

Two design consequences worth stating:

* **Repairs are recorded as replacements, not as rewrites of history.** A joined
  hyphenated word maps back to the span that contained the hyphen and the line
  break. Callers that need the untouched characters — for instance
  :class:`~aleph.core.models.Quantity`, whose ``raw_text`` is contractually the
  text *before* normalisation — call :meth:`NormalizedDocument.original_slice`.
* **Running headers are removed on evidence, not on suspicion.** A line is only
  stripped when the same shape (with digits masked, so page numbers collapse
  together) recurs at the top or bottom of a clear majority of pages. On a
  three-page document there is not enough evidence to conclude anything, so
  nothing is removed.

Nothing in this module knows what language, jurisdiction or kind of document it
is cleaning.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from aleph.core.enums import ExtractionWarningCode, WarningSeverity
from aleph.core.models import ExtractionWarning, Span
from aleph.ingestion.pdf import ExtractedDocument

__all__ = [
    "NORMALIZER_VERSION",
    "NormalizeOptions",
    "OffsetMap",
    "NormalizedPage",
    "NormalizedDocument",
    "normalize_document",
    "normalize_text",
    "fold_accents",
    "fold_preserving_length",
    "collapse_signature",
]

#: Version of the normalisation rules. A span recorded under one version cannot
#: be assumed to line up with text produced by another.
NORMALIZER_VERSION: Final[str] = "aleph.ingestion.normalize/1.0.0"


# ---------------------------------------------------------------------------
# Substitution tables (data, not scattered literals)
# ---------------------------------------------------------------------------

#: Characters replaced one-for-one or one-for-many. Grouped by why they are here.
_CHAR_SUBSTITUTIONS: Final[dict[str, str]] = {
    # Typographic ligatures. Extractors emit these as single codepoints and every
    # word containing one becomes unsearchable and unmatchable.
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
    # Deliberately absent: æ, œ, ĳ. Those are letters of living alphabets, not
    # typesetting artefacts, and expanding them would corrupt Danish, Norwegian,
    # French and Dutch text in the name of tidying up an English-language habit.
    # Dashes. Folded to ASCII hyphen so that numeric ranges, compound words and
    # list bullets match one pattern instead of seven. The original character is
    # always recoverable through the offset map.
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    "⁃": "-",
    "﹘": "-",
    "﹣": "-",
    "－": "-",
    # Quotation marks and apostrophes.
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "′": "'",
    "´": "'",
    "`": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "″": '"',
    "«": '"',
    "»": '"',
    # Spaces that are not the space character. Left as-is these break every
    # word-boundary and number-format pattern in the codebase.
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    "　": " ",
    # Invisible characters that survive extraction and silently split words.
    "­": "",
    "​": "",
    "‌": "",
    "‍": "",
    "⁠": "",
    "﻿": "",
    # Line and paragraph separators that are not '\n'.
    " ": "\n",
    " ": "\n",
    # Common single-codepoint punctuation that regexes would otherwise miss.
    "…": "...",
    "˜": "~",
}

_CHAR_SUBSTITUTION_RE: Final[re.Pattern[str]] = re.compile(
    "[" + re.escape("".join(_CHAR_SUBSTITUTIONS)) + "]"
)

#: A word cut in half by a line-wrapping hyphen. Requires a letter on both sides
#: and exactly one newline, so a genuine em-dash aside or a page break is never
#: joined. The trailing letter is a lookahead so that consecutive hyphenated
#: wraps ("estable-\ncimien-\nto") are all found in one pass.
_HYPHEN_BREAK_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<before>[^\W\d_])-[ \t]*\n[ \t]*(?=(?P<after>[^\W\d_]))"
)

#: Horizontal whitespace runs, collapsed to a single space.
_HSPACE_RUN_RE: Final[re.Pattern[str]] = re.compile(r"[ \t\v\f\r]+")

#: Whitespace hugging a newline, plus runs of two or more newlines.
_VSPACE_RUN_RE: Final[re.Pattern[str]] = re.compile(
    r"[ \t\r]*\n(?:[ \t\r]*\n)+[ \t\r]*|[ \t\r]*\n[ \t\r]*"
)

#: Digit runs, masked when comparing candidate running headers so that
#: "Page 3 of 80" and "Page 4 of 80" are recognised as the same header.
_DIGIT_RUN_RE: Final[re.Pattern[str]] = re.compile(r"\d+")

_COMBINING_RE: Final[re.Pattern[str]] = re.compile(r"[̀-ͯ]")


def fold_accents(text: str) -> str:
    """Strip diacritics and lowercase, for accent-insensitive matching.

    Every cue table in :mod:`aleph.documents` is written in folded ASCII and
    matched against folded text. That is not cosmetic: documents are inconsistent
    about accents (``ARTICULO`` and ``ARTÍCULO`` appear in the same file, and
    extraction sometimes loses the accent altogether), and a cue list that missed
    half its hits because of a diacritic would silently under-extract from one
    language while working fine in another.

    Length is not preserved, so this must never be used on text whose offsets
    matter; it is a comparison key only.
    """
    decomposed = unicodedata.normalize("NFD", text)
    return _COMBINING_RE.sub("", decomposed).lower()


def _build_fold_table() -> dict[int, str]:
    """Build a one-codepoint-to-one-codepoint diacritic-stripping table.

    Derived from Unicode's own decompositions rather than hand-listed, so it
    covers the whole Latin range without a table anyone has to maintain. A few
    letters that carry no decomposition (ø, ł, đ, ı, ß) are added explicitly,
    always as a single character, because the length guarantee is the whole point.
    """
    table: dict[int, str] = {}
    for codepoint in range(0x00C0, 0x0250):
        char = chr(codepoint)
        base = unicodedata.normalize("NFD", char)[0]
        if base != char and base.isascii() and base.isalpha():
            table[codepoint] = base
    table.update(
        {
            ord("ø"): "o",
            ord("Ø"): "O",
            ord("ł"): "l",
            ord("Ł"): "L",
            ord("đ"): "d",
            ord("Đ"): "D",
            ord("ħ"): "h",
            ord("ı"): "i",
            ord("İ"): "I",
            ord("ŧ"): "t",
            ord("ß"): "s",
            ord("ẞ"): "S",
        }
    )
    return table


_FOLD_TABLE: Final[dict[int, str]] = _build_fold_table()


def fold_preserving_length(text: str) -> str:
    """Fold diacritics and case *without* changing any character's position.

    :func:`fold_accents` is the right tool for comparing two strings. It is the
    wrong tool for scanning a document, because NFD decomposition inserts
    combining marks and every offset after the first accented character shifts —
    which would silently corrupt every span a cue match produced.

    This variant maps each accented codepoint to exactly one ASCII codepoint, so
    ``len(fold_preserving_length(s)) == len(s)`` and a match found in the folded
    text can be sliced straight out of the original. Every cue-scanning pattern
    in :mod:`aleph.documents` relies on that invariant.
    """
    return text.translate(_FOLD_TABLE).lower()


def collapse_signature(line: str) -> str:
    """Reduce a line to the shape used for running-header comparison.

    Digits become ``#`` so that page numbers, dates and section counters do not
    make each page's header look unique — which is precisely the trap that lets
    eighty copies of one footer through.
    """
    return _DIGIT_RUN_RE.sub("#", " ".join(fold_accents(line).split()))


# ---------------------------------------------------------------------------
# Offset mapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Segment:
    """One contiguous piece of output and the input region that produced it.

    ``linear`` marks a segment copied verbatim, where an offset can be
    interpolated exactly. Non-linear segments are substitutions and collapses,
    where the honest answer for an interior offset is the start of the region
    that was replaced.
    """

    out_start: int
    out_end: int
    src_start: int
    src_end: int
    linear: bool


class OffsetMap:
    """A translation from offsets in normalised text back to the original.

    Maps compose: each normalisation pass builds a map from its own output to its
    own input, and links to the pass before it. :meth:`to_original` walks the
    whole chain, so a caller only ever deals with two coordinate systems — the
    cleaned text it is analysing, and the raw extraction it must be able to cite.

    Lookups are ``O(log n)`` per pass via binary search over segment starts.
    """

    __slots__ = ("_segments", "_starts", "_previous", "_out_length", "_src_length")

    def __init__(
        self,
        segments: Sequence[_Segment],
        *,
        out_length: int,
        src_length: int,
        previous: OffsetMap | None = None,
    ) -> None:
        self._segments: tuple[_Segment, ...] = tuple(segments)
        self._starts: tuple[int, ...] = tuple(seg.out_start for seg in self._segments)
        self._previous = previous
        self._out_length = out_length
        self._src_length = src_length

    @classmethod
    def identity(cls, length: int, *, previous: OffsetMap | None = None) -> OffsetMap:
        """A map that changes nothing, for the no-op case."""
        return cls(
            [_Segment(0, length, 0, length, True)] if length else [],
            out_length=length,
            src_length=length,
            previous=previous,
        )

    @property
    def output_length(self) -> int:
        return self._out_length

    def _to_source(self, offset: int) -> int:
        """Map one offset from this pass's output to this pass's input."""
        if offset <= 0:
            return 0
        if not self._segments or offset >= self._out_length:
            return self._src_length
        index = bisect_right(self._starts, offset) - 1
        if index < 0:
            return self._segments[0].src_start
        seg = self._segments[index]
        if offset >= seg.out_end:
            # Inside a region whose output was dropped entirely: the next
            # surviving character is the honest anchor.
            return seg.src_end
        if seg.linear:
            return seg.src_start + (offset - seg.out_start)
        return seg.src_start

    def _to_source_end(self, offset: int) -> int:
        """Map an exclusive end offset, keeping the span tight rather than wide.

        Using :meth:`_to_source` on an end offset would push the boundary past
        any material that was dropped immediately after the span, quietly
        widening every quotation.
        """
        if offset <= 0:
            return 0
        if not self._segments or offset >= self._out_length:
            return self._src_length
        index = bisect_right(self._starts, offset - 1) - 1
        if index < 0:
            return self._segments[0].src_start
        seg = self._segments[index]
        if offset > seg.out_end:
            return seg.src_end
        if seg.linear:
            return seg.src_start + (offset - seg.out_start)
        return seg.src_end

    def to_original(self, offset: int) -> int:
        """Translate a normalised-text offset all the way back to the extraction."""
        current = offset
        mapper: OffsetMap | None = self
        while mapper is not None:
            current = mapper._to_source(current)
            mapper = mapper._previous
        return current

    def to_original_end(self, offset: int) -> int:
        """Translate an exclusive end offset back to the extraction."""
        current = offset
        mapper: OffsetMap | None = self
        while mapper is not None:
            current = mapper._to_source_end(current)
            mapper = mapper._previous
        return current

    def to_original_range(self, start: int, end: int) -> tuple[int, int]:
        """Translate a normalised half-open range back to the extraction.

        The result is guaranteed non-inverted: a range that collapsed to nothing
        during normalisation reports as a zero-width point rather than as a
        negative span that would crash a slice.
        """
        origin = self.to_original(start)
        finish = self.to_original_end(end)
        return (origin, max(origin, finish))


class _Rewriter:
    """Builds one normalisation pass's output while recording its offset map.

    Operations are emitted strictly left to right and each advances a cursor over
    the source, so it is impossible to build an output whose map does not account
    for every input character. ``marks`` are input offsets — page boundaries —
    whose position in the output is resolved as the cursor passes them, which is
    what lets page ranges survive four passes of editing.
    """

    __slots__ = ("_source", "_out", "_segments", "_length", "_cursor", "_marks", "_resolved", "_mi")

    def __init__(self, source: str, marks: Sequence[int] = ()) -> None:
        self._source = source
        self._out: list[str] = []
        self._segments: list[_Segment] = []
        self._length = 0
        self._cursor = 0
        self._marks = sorted(marks)
        self._resolved: list[int] = []
        self._mi = 0

    @property
    def cursor(self) -> int:
        """Next source offset that has not yet been emitted or dropped."""
        return self._cursor

    def _emit(self, end: int, text: str | None) -> None:
        start = self._cursor
        if end < start:
            raise ValueError(f"rewriter cannot move backwards: {end} < {start}")
        content = self._source[start:end] if text is None else text
        linear = text is None
        out_start = self._length
        if content:
            self._out.append(content)
            self._length += len(content)
            self._segments.append(
                _Segment(
                    out_start, self._length, start, end, linear and end - start == len(content)
                )
            )
        elif end > start:
            # A pure deletion: record it so offsets inside it resolve forward to
            # the next surviving character rather than being silently lost.
            self._segments.append(_Segment(out_start, out_start, start, end, False))
        while self._mi < len(self._marks) and self._marks[self._mi] < end:
            mark = self._marks[self._mi]
            if linear and content:
                self._resolved.append(out_start + max(0, mark - start))
            else:
                self._resolved.append(out_start)
            self._mi += 1
        self._cursor = end

    def keep_until(self, end: int) -> None:
        """Copy source up to ``end`` verbatim."""
        self._emit(end, None)

    def replace_until(self, end: int, text: str) -> None:
        """Replace source up to ``end`` with ``text``."""
        self._emit(end, text)

    def drop_until(self, end: int) -> None:
        """Delete source up to ``end``."""
        self._emit(end, "")

    def finish(self, previous: OffsetMap | None = None) -> tuple[str, OffsetMap, list[int]]:
        """Flush the remaining source and return output, map and resolved marks."""
        if self._cursor < len(self._source):
            self.keep_until(len(self._source))
        while self._mi < len(self._marks):
            # Anything still unresolved sat at or past the end of the source, so
            # it belongs at the end of the output.
            self._resolved.append(self._length)
            self._mi += 1
        text = "".join(self._out)
        mapping = OffsetMap(
            self._segments,
            out_length=len(text),
            src_length=len(self._source),
            previous=previous,
        )
        return text, mapping, list(self._resolved)


# ---------------------------------------------------------------------------
# Options and results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormalizeOptions:
    """Knobs for normalisation, each with a reason to exist.

    Defaults are the conservative ones. In particular ``running_line_ratio`` is
    high and ``min_pages_for_running_lines`` is above two, because deleting a
    line that turned out not to be a header removes real content from the
    analysis, whereas keeping one merely adds noise a later stage can ignore.
    """

    substitute_characters: bool = True
    repair_hyphenation: bool = True
    collapse_whitespace: bool = True
    strip_running_lines: bool = True

    running_line_ratio: float = 0.6
    """Fraction of pages a line shape must appear on to count as a running line."""

    min_pages_for_running_lines: int = 3
    """Below this page count there is not enough evidence to call anything a header."""

    running_line_scan: int = 3
    """How many lines at each end of a page are considered."""

    max_running_line_chars: int = 160
    """Longer lines are body text that happens to repeat, not furniture."""


@dataclass(frozen=True, slots=True)
class NormalizedPage:
    """Where one source page ended up in the normalised text."""

    page_number: int
    char_start: int
    char_end: int

    def contains(self, offset: int) -> bool:
        return self.char_start <= offset < self.char_end


@dataclass(frozen=True)
class NormalizedDocument:
    """Cleaned document text that still knows where every character came from.

    This is the object every later phase reads. It carries the normalised text
    for analysis, the original extraction for verbatim quotation, the page
    boundaries needed to report a span the way the data contract requires, and
    the map that connects the three.
    """

    text: str
    original_text: str
    pages: tuple[NormalizedPage, ...]
    offsets: OffsetMap
    warnings: tuple[ExtractionWarning, ...] = ()
    removed_running_lines: tuple[str, ...] = ()
    normalizer_version: str = NORMALIZER_VERSION
    _page_starts: tuple[int, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_page_starts", tuple(page.char_start for page in self.pages))

    def __len__(self) -> int:
        return len(self.text)

    def page_at(self, offset: int) -> NormalizedPage | None:
        """Return the page a normalised offset falls in, or ``None`` if unpaged."""
        if not self.pages:
            return None
        index = bisect_right(self._page_starts, offset) - 1
        if index < 0:
            return self.pages[0]
        return self.pages[index]

    def page_number_at(self, offset: int) -> int | None:
        page = self.page_at(offset)
        return page.page_number if page else None

    def original_slice(self, start: int, end: int) -> str:
        """Return the untouched extraction text behind a normalised range.

        Used wherever the contract asks for pre-normalisation text — most
        importantly :attr:`~aleph.core.models.Quantity.raw_text`, which exists so
        that a decimal-separator misreading can be audited against what the page
        literally said.
        """
        origin, finish = self.offsets.to_original_range(start, end)
        return self.original_text[origin:finish]

    def to_span(
        self,
        start: int,
        end: int,
        *,
        section_id: str | None = None,
        max_chars: int | None = None,
    ) -> Span:
        """Build a contract :class:`~aleph.core.models.Span` for a normalised range.

        Character offsets are made page-relative, as ``common.json`` specifies,
        and ``text`` is the normalised passage so that the quotation and the
        offsets describe the same string — a UI highlighting ``char_start`` to
        ``char_end`` must land on exactly the words it displays.

        Args:
            start: Inclusive start offset in :attr:`text`.
            end: Exclusive end offset in :attr:`text`.
            section_id: Outline node the passage belongs to, when known.
            max_chars: Truncate the quoted text beyond this length. Offsets are
                left describing the full range, so nothing becomes unlocatable.
        """
        start = max(0, min(start, len(self.text)))
        end = max(start, min(end, len(self.text)))
        passage = self.text[start:end]
        if max_chars is not None and len(passage) > max_chars:
            passage = passage[: max(0, max_chars - 1)].rstrip() + "…"
        page = self.page_at(start)
        if page is None:
            return Span(
                page=None,
                section_id=section_id,
                char_start=start,
                char_end=end,
                text=passage,
            )
        return Span(
            page=page.page_number,
            section_id=section_id,
            char_start=max(0, start - page.char_start),
            char_end=max(0, end - page.char_start),
            text=passage,
        )


# ---------------------------------------------------------------------------
# The passes
# ---------------------------------------------------------------------------


def normalize_document(
    extracted: ExtractedDocument,
    *,
    options: NormalizeOptions | None = None,
) -> NormalizedDocument:
    """Clean an extracted document, keeping every offset traceable.

    Passes run in a fixed order, and the order is load-bearing:

    1. **Running headers and footers** first, while page boundaries still line up
       with the extraction and a line's position on its page is still known.
    2. **Character substitutions**, so that later passes see ASCII hyphens and
       ordinary spaces rather than seven dash variants.
    3. **Hyphenation repair**, which depends on step 2 having produced a plain
       ``-`` and having deleted soft hyphens.
    4. **Whitespace collapse** last, because it destroys the line structure the
       earlier passes rely on.

    Args:
        extracted: The located extraction to clean.
        options: Overrides; the defaults are the conservative settings.

    Returns:
        A :class:`NormalizedDocument` whose ``warnings`` record anything a reader
        should know about what was changed.
    """
    opts = options or NormalizeOptions()
    text = extracted.text
    marks: list[int] = []
    for page in extracted.pages:
        marks.extend((page.char_start, page.char_end))

    warnings: list[ExtractionWarning] = []
    mapping: OffsetMap | None = None
    removed: tuple[str, ...] = ()

    if opts.strip_running_lines and len(extracted.pages) >= opts.min_pages_for_running_lines:
        text, mapping, marks, removed = _strip_running_lines(text, marks, opts, mapping)
        if removed:
            warnings.append(
                ExtractionWarning(
                    code=ExtractionWarningCode.OTHER,
                    severity=WarningSeverity.INFO,
                    message=(
                        f"{len(removed)} repeating running header/footer line(s) were "
                        "removed before analysis so they would not be read as headings "
                        f"or provisions: {'; '.join(repr(line) for line in removed[:5])}"
                    ),
                    affected_field="structure.sections",
                )
            )

    if opts.substitute_characters:
        text, mapping, marks = _substitute_characters(text, marks, mapping)
    if opts.repair_hyphenation:
        text, mapping, marks, joined = _repair_hyphenation(text, marks, mapping)
        if joined:
            warnings.append(
                ExtractionWarning(
                    code=ExtractionWarningCode.OTHER,
                    severity=WarningSeverity.INFO,
                    message=(
                        f"{joined} word(s) split across line ends by a wrapping hyphen "
                        "were rejoined; quoted passages therefore differ from the raw "
                        "extraction at those points, and original_slice() recovers the "
                        "untouched characters"
                    ),
                )
            )
    if opts.collapse_whitespace:
        text, mapping, marks = _collapse_whitespace(text, marks, mapping)

    if mapping is None:
        mapping = OffsetMap.identity(len(text))

    pages = _pages_from_marks(extracted, marks, len(text))
    return NormalizedDocument(
        text=text,
        original_text=extracted.text,
        pages=pages,
        offsets=mapping,
        warnings=tuple(warnings),
        removed_running_lines=removed,
    )


def normalize_text(
    text: str,
    *,
    options: NormalizeOptions | None = None,
    page_separator: str = "\f",
) -> NormalizedDocument:
    """Normalise a plain string, for tests and for non-PDF inputs.

    A convenience wrapper over :func:`normalize_document` that first wraps the
    string in the same located structure a PDF would produce, so that heading
    detection, quantity extraction and provision segmentation can all be
    exercised on a five-line fixture.
    """
    from aleph.ingestion.pdf import extract_plain_text

    return normalize_document(
        extract_plain_text(text, page_separator=page_separator), options=options
    )


def _pages_from_marks(
    extracted: ExtractedDocument,
    marks: Sequence[int],
    length: int,
) -> tuple[NormalizedPage, ...]:
    """Rebuild page ranges from the marks carried through every pass."""
    pages: list[NormalizedPage] = []
    for index, page in enumerate(extracted.pages):
        start_index, end_index = index * 2, index * 2 + 1
        start = marks[start_index] if start_index < len(marks) else length
        end = marks[end_index] if end_index < len(marks) else length
        start = max(0, min(start, length))
        end = max(start, min(end, length))
        pages.append(NormalizedPage(page_number=page.page_number, char_start=start, char_end=end))
    if pages:
        # The last page owns everything up to the end of the text, so no offset
        # can fall outside every page and lose its page number.
        last = pages[-1]
        pages[-1] = NormalizedPage(last.page_number, last.char_start, length)
    return tuple(pages)


def _iter_lines(text: str, start: int, end: int) -> Iterable[tuple[int, int, str]]:
    """Yield ``(start, end, content)`` for each line in ``text[start:end]``."""
    cursor = start
    while cursor < end:
        newline = text.find("\n", cursor, end)
        stop = end if newline == -1 else newline
        yield cursor, stop, text[cursor:stop]
        if newline == -1:
            return
        cursor = newline + 1


def _strip_running_lines(
    text: str,
    marks: Sequence[int],
    opts: NormalizeOptions,
    previous: OffsetMap | None,
) -> tuple[str, OffsetMap, list[int], tuple[str, ...]]:
    """Remove headers and footers that repeat across a majority of pages.

    Repetition is judged on a digit-masked signature so that ``Page 3 of 80`` and
    ``Page 4 of 80`` count as the same line. Position matters as well as text: a
    phrase that recurs in the body is content, and only lines near the top or
    bottom edge of a page are candidates for removal.
    """
    page_ranges = [
        (marks[i], marks[i + 1]) for i in range(0, len(marks) - 1, 2) if marks[i] <= marks[i + 1]
    ]
    page_count = len(page_ranges)
    if page_count < opts.min_pages_for_running_lines:
        return text, OffsetMap.identity(len(text), previous=previous), list(marks), ()

    # (position, signature) -> list of (line_start, line_end)
    seen: dict[tuple[str, str], list[tuple[int, int]]] = {}
    pages_for: dict[tuple[str, str], set[int]] = {}

    for page_index, (start, end) in enumerate(page_ranges):
        lines = [
            (line_start, line_end, content)
            for line_start, line_end, content in _iter_lines(text, start, end)
            if content.strip()
        ]
        head = lines[: opts.running_line_scan]
        foot = lines[-opts.running_line_scan :] if len(lines) > opts.running_line_scan else []
        for position, group in (("head", head), ("foot", foot)):
            for line_start, line_end, content in group:
                stripped = content.strip()
                if not stripped or len(stripped) > opts.max_running_line_chars:
                    continue
                key = (position, collapse_signature(stripped))
                if not key[1]:
                    continue
                seen.setdefault(key, []).append((line_start, line_end))
                pages_for.setdefault(key, set()).add(page_index)

    threshold = max(2, round(opts.running_line_ratio * page_count))
    doomed: list[tuple[int, int]] = []
    removed: list[str] = []
    for key, occurrences in seen.items():
        if len(pages_for[key]) < threshold:
            continue
        removed.append(key[1])
        doomed.extend(occurrences)

    if not doomed:
        return text, OffsetMap.identity(len(text), previous=previous), list(marks), ()

    doomed.sort()
    rewriter = _Rewriter(text, marks)
    for line_start, line_end in doomed:
        # Take the trailing newline with the line; failing that, the leading one,
        # so removal does not leave a blank line where the header used to be.
        drop_start, drop_end = line_start, line_end
        if drop_end < len(text) and text[drop_end] == "\n":
            drop_end += 1
        elif drop_start > 0 and text[drop_start - 1] == "\n":
            drop_start -= 1
        if drop_start < rewriter.cursor:
            continue
        rewriter.keep_until(drop_start)
        rewriter.drop_until(drop_end)
    new_text, mapping, new_marks = rewriter.finish(previous)
    return new_text, mapping, new_marks, tuple(sorted(set(removed)))


def _substitute_characters(
    text: str,
    marks: Sequence[int],
    previous: OffsetMap | None,
) -> tuple[str, OffsetMap, list[int]]:
    """Apply the character substitution table, recording every replacement."""
    rewriter = _Rewriter(text, marks)
    for match in _CHAR_SUBSTITUTION_RE.finditer(text):
        rewriter.keep_until(match.start())
        rewriter.replace_until(match.end(), _CHAR_SUBSTITUTIONS[match.group(0)])
    return rewriter.finish(previous)


def _repair_hyphenation(
    text: str,
    marks: Sequence[int],
    previous: OffsetMap | None,
) -> tuple[str, OffsetMap, list[int], int]:
    """Rejoin words broken across a line end by a wrapping hyphen.

    The hyphen is kept when the continuation starts with a capital, because
    ``Anglo-\\nSaxon`` is a real compound rather than a wrap, and dropped
    otherwise. Both cases are recorded as replacements, so the original hyphen
    and newline remain reachable through the map.
    """
    rewriter = _Rewriter(text, marks)
    joined = 0
    for match in _HYPHEN_BREAK_RE.finditer(text):
        after = match.group("after")
        # Span between the two letters: the hyphen, the newline and any indent.
        gap_start = match.start("before") + 1
        gap_end = match.start("after")
        if gap_start < rewriter.cursor:
            continue
        rewriter.keep_until(gap_start)
        rewriter.replace_until(gap_end, "-" if after.isupper() else "")
        joined += 1
    new_text, mapping, new_marks = rewriter.finish(previous)
    return new_text, mapping, new_marks, joined


def _collapse_whitespace(
    text: str,
    marks: Sequence[int],
    previous: OffsetMap | None,
) -> tuple[str, OffsetMap, list[int]]:
    """Normalise runs of whitespace while preserving paragraph structure.

    Horizontal runs become one space; a single line break stays a single line
    break; two or more become exactly two. Line structure survives because
    heading detection reads lines, and paragraph structure survives because
    provision segmentation reads blank lines.
    """
    rewriter = _Rewriter(text, marks)
    for match in _VSPACE_RUN_RE.finditer(text):
        run = match.group(0)
        replacement = "\n\n" if run.count("\n") >= 2 else "\n"
        if run == replacement:
            continue
        if match.start() < rewriter.cursor:
            continue
        rewriter.keep_until(match.start())
        rewriter.replace_until(match.end(), replacement)
    stage_one, map_one, marks_one = rewriter.finish(previous)

    rewriter = _Rewriter(stage_one, marks_one)
    for match in _HSPACE_RUN_RE.finditer(stage_one):
        if match.group(0) == " ":
            continue
        if match.start() < rewriter.cursor:
            continue
        rewriter.keep_until(match.start())
        rewriter.replace_until(match.end(), " ")
    return rewriter.finish(map_one)
