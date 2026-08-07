"""The failures Aleph is willing to admit to, and the context each one carries.

An evidence-analysis system fails in a distinctive way: not by crashing, but by
producing a plausible answer built on something that quietly did not work. A
scanned page that yielded no text becomes a document with no provisions, which
becomes a claim with no primary source, which becomes a confident verdict resting
on nothing. Every exception in this module exists to interrupt that chain at the
point where the ground gave way, and to carry enough context that the resulting
gap can be reported to a reader as a gap rather than absorbed into a score.

Two design rules follow from that.

**Failures are typed by what a caller can do about them.** ``ProviderError``
means retry or switch provider; ``UnsupportedDocumentError`` means no retry will
help; ``InsufficientEvidenceError`` means the analysis was correct to stop and
the honest output is the list of gaps. Collapsing these into one exception would
force every caller to parse a message string to decide.

**Failures carry structured context, not just prose.** Each class pins named
fields that downstream code and the API layer can render without re-parsing.
``str(exc)`` appends them in a stable order so logs are greppable.

Note what is deliberately absent: there is no exception for "the claim was
false". A false claim is a *result* — a ``contradicted`` verdict — not an error.
Likewise ``InsufficientEvidenceError`` is raised when the pipeline is asked to
produce a verdict it has no basis for; the ordinary handling of thin evidence is
an ``insufficient`` readiness state, published rather than raised.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AlephError",
    "DocumentParseError",
    "UnsupportedDocumentError",
    "SchemaMismatchError",
    "RetrievalError",
    "RetrievalDisabledError",
    "ProviderError",
    "InsufficientEvidenceError",
    "NeutralityViolationError",
]


class AlephError(Exception):
    """Base class for every error Aleph raises deliberately.

    Carries a free-form ``context`` mapping alongside the message so that a
    handler can render structured detail (which page, which source, which
    claim) without scraping a formatted string. Subclasses promote the fields
    that matter for their failure mode into named attributes and mirror them
    into ``context``.

    Attributes:
        message: Human-readable statement of what went wrong.
        context: Structured detail, ``None`` values omitted.
    """

    def __init__(self, message: str, **context: Any) -> None:
        self.message = message
        self.context: dict[str, Any] = {k: v for k, v in context.items() if v is not None}
        super().__init__(message)

    def __str__(self) -> str:
        if not self.context:
            return self.message
        detail = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
        return f"{self.message} ({detail})"

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.message!r}, **{self.context!r})"

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping for API responses and logs.

        Never includes a traceback or a filesystem path beyond what a caller
        explicitly put in ``context``; error payloads leave the process and must
        not become an information-disclosure channel.
        """
        return {
            "error": type(self).__name__,
            "message": self.message,
            "context": dict(self.context),
        }


class DocumentParseError(AlephError):
    """A document was reachable and of a supported kind, but could not be read.

    Distinguished from :class:`UnsupportedDocumentError` because this one is
    often partial and often recoverable: three unreadable pages in a
    forty-page instrument still leave thirty-seven pages of usable evidence. The
    page and stage are recorded so the resulting hole can be published as an
    extraction warning rather than silently narrowing what the analysis saw.

    Attributes:
        source: Where the bytes came from (path, URL or fixture name).
        page: 1-based page number where parsing failed, when it was page-local.
        stage: Which step failed, e.g. ``'text_extraction'``, ``'sectioning'``.
        recoverable: Whether the pipeline may continue with a partial reading
            and record an extraction warning, or must abandon the document.
    """

    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        page: int | None = None,
        stage: str | None = None,
        recoverable: bool = False,
        **context: Any,
    ) -> None:
        self.source = source
        self.page = page
        self.stage = stage
        self.recoverable = recoverable
        super().__init__(
            message,
            source=source,
            page=page,
            stage=stage,
            recoverable=recoverable,
            **context,
        )


class UnsupportedDocumentError(AlephError):
    """The input is not something Aleph can analyse at all.

    Raised at the door, before any extraction is attempted: a video file, an
    encrypted PDF with no password, a file over the configured size limit. This
    is a terminal condition — no retry and no fallback extractor will help — and
    it is reported as a refusal rather than as an empty analysis, because an
    empty analysis of an unreadable file looks exactly like an analysis of a
    document that says nothing.

    Attributes:
        media_type: Detected IANA media type, when one was determined.
        detected: What the sniffer actually saw, when it disagrees with the
            declared type.
        reason: Why the input cannot be handled, in terms a user can act on.
        size_bytes: Size of the input, populated when the limit was the reason.
    """

    def __init__(
        self,
        message: str,
        *,
        media_type: str | None = None,
        detected: str | None = None,
        reason: str | None = None,
        size_bytes: int | None = None,
        **context: Any,
    ) -> None:
        self.media_type = media_type
        self.detected = detected
        self.reason = reason
        self.size_bytes = size_bytes
        super().__init__(
            message,
            media_type=media_type,
            detected=detected,
            reason=reason,
            size_bytes=size_bytes,
            **context,
        )


class SchemaMismatchError(AlephError):
    """Data does not conform to the published Aleph data contract.

    This is the error that keeps the contract real. The schemas in ``/schemas``
    are not documentation: they are the interface the frontend, the API and
    every downstream consumer are written against, and an object that drifts
    from them must fail loudly at the boundary rather than reach a reader as a
    silently missing field. Raised both when Aleph is about to emit something
    invalid and when it is handed something invalid.

    Attributes:
        schema_name: Schema the data was checked against, e.g. ``'claim'``.
        pointer: JSON Pointer to the offending location, e.g.
            ``'/claims/3/blind_evaluation/verdict'``.
        expected: What the contract requires there.
        actual: What was found, rendered safely.
    """

    def __init__(
        self,
        message: str,
        *,
        schema_name: str | None = None,
        pointer: str | None = None,
        expected: Any = None,
        actual: Any = None,
        **context: Any,
    ) -> None:
        self.schema_name = schema_name
        self.pointer = pointer
        self.expected = expected
        self.actual = actual
        super().__init__(
            message,
            schema_name=schema_name,
            pointer=pointer,
            expected=expected,
            actual=actual,
            **context,
        )


class RetrievalError(AlephError):
    """Evidence could not be collected from a source.

    Retrieval failures are first-class evidence about the evidence base: a
    paywalled source that could not be read is a coverage gap that readiness
    must report, not an absence of coverage. Callers are expected to convert
    these into recorded retrieval gaps rather than to swallow them.

    Attributes:
        url: The location that failed.
        source_id: Registry id of the source, when the fetch was registry-driven.
        status_code: HTTP status, when there was one.
        reason: Short machine-friendly cause, e.g. ``'timeout'``, ``'paywall'``,
            ``'robots_disallow'``.
        retryable: Whether a later attempt could plausibly succeed.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        source_id: str | None = None,
        status_code: int | None = None,
        reason: str | None = None,
        retryable: bool = False,
        **context: Any,
    ) -> None:
        self.url = url
        self.source_id = source_id
        self.status_code = status_code
        self.reason = reason
        self.retryable = retryable
        super().__init__(
            message,
            url=url,
            source_id=source_id,
            status_code=status_code,
            reason=reason,
            retryable=retryable,
            **context,
        )


class RetrievalDisabledError(RetrievalError):
    """A network fetch was attempted while retrieval was not enabled.

    Aleph's default retrieval mode is ``manual``: no module may reach the
    network as a side effect of running the pipeline. This exception is what
    makes that a guarantee rather than an intention — code that forgets to pass
    ``allow_network=True`` fails loudly at the call site instead of quietly
    emitting traffic to a stranger's server, and a run's reproducibility is
    preserved because nothing can change underneath it mid-analysis.

    Attributes:
        mode: The active retrieval mode that forbade the call.
        operation: What was attempted, e.g. ``'fetch_article'``.
        how_to_enable: The explicit, deliberate action that would permit it.
    """

    def __init__(
        self,
        message: str = "network retrieval is disabled for this run",
        *,
        mode: str | None = None,
        operation: str | None = None,
        how_to_enable: str | None = (
            "pass allow_network=True at the call site, or run the refresh CLI with --fetch"
        ),
        **context: Any,
    ) -> None:
        self.mode = mode
        self.operation = operation
        self.how_to_enable = how_to_enable
        super().__init__(
            message,
            reason="retrieval_disabled",
            retryable=False,
            mode=mode,
            operation=operation,
            how_to_enable=how_to_enable,
            **context,
        )


class ProviderError(AlephError):
    """A language-model or search provider failed to answer.

    Kept separate from :class:`RetrievalError` because the remedy differs: a
    provider failure is about Aleph's own infrastructure and may be retried or
    routed to the deterministic mock, whereas a retrieval failure is a fact
    about the evidence base that a reader is entitled to see.

    Attributes:
        provider: Provider name, e.g. ``'qwen'``, ``'mock'``.
        operation: What was being asked for, e.g. ``'complete'``, ``'search'``.
        status_code: Transport status, when there was one.
        retryable: Whether a retry is worth attempting.
        detail: Provider-side message, already stripped of credentials.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        operation: str | None = None,
        status_code: int | None = None,
        retryable: bool = False,
        detail: str | None = None,
        **context: Any,
    ) -> None:
        self.provider = provider
        self.operation = operation
        self.status_code = status_code
        self.retryable = retryable
        self.detail = detail
        super().__init__(
            message,
            provider=provider,
            operation=operation,
            status_code=status_code,
            retryable=retryable,
            detail=detail,
            **context,
        )


class InsufficientEvidenceError(AlephError):
    """A verdict was demanded where the evidence cannot support one.

    This is Aleph declining rather than Aleph breaking. The ordinary path for
    thin evidence is to publish it as thin — an ``insufficient`` readiness
    state, an ``unverifiable`` verdict, a named gap — and this exception exists
    for the narrower case where a caller has asked for a conclusion the evidence
    base structurally cannot license. Raising is correct here precisely because
    the alternative, returning a confident-sounding answer, is the failure mode
    the whole product exists to prevent.

    Attributes:
        question: The question that could not be answered.
        claim_id: The claim under evaluation, when there was one.
        evidence_count: How many items were available.
        independent_source_count: How many distinct originals those items
            collapse to. Usually the number that actually falls short: ten
            copies of one wire report are one source.
        required: The minimum the caller demanded.
        gaps: Named, actionable holes — what to go and get.
    """

    def __init__(
        self,
        message: str,
        *,
        question: str | None = None,
        claim_id: str | None = None,
        evidence_count: int | None = None,
        independent_source_count: int | None = None,
        required: int | None = None,
        gaps: list[str] | None = None,
        **context: Any,
    ) -> None:
        self.question = question
        self.claim_id = claim_id
        self.evidence_count = evidence_count
        self.independent_source_count = independent_source_count
        self.required = required
        self.gaps: list[str] = list(gaps) if gaps else []
        super().__init__(
            message,
            question=question,
            claim_id=claim_id,
            evidence_count=evidence_count,
            independent_source_count=independent_source_count,
            required=required,
            gaps=self.gaps or None,
            **context,
        )


class NeutralityViolationError(AlephError):
    """An evaluation changed when only an evidentially irrelevant detail changed.

    Raised when the perturbation harness is run in enforcing mode and a verdict
    moves after a speaker, an outlet, a party label, an authority cue, a
    paraphrase or the evidence ordering was swapped. Nothing evidentially
    relevant was altered, so the change is by construction a defect in Aleph
    itself — a leak of identity into the factual path that
    :class:`~aleph.core.models.RedactedClaimContext` is meant to make
    structurally impossible.

    A flip is normally *reported* in the neutrality report rather than raised;
    this exception is for the gate that must fail a build or block a
    publication.

    Attributes:
        perturbation: Which of the six families produced the change.
        claim_id: The claim whose evaluation moved.
        original_verdict: Verdict before the substitution.
        perturbed_verdict: Verdict after it.
        confidence_delta: Change in evidence confidence, which should be ~0.
        flip_rate: Aggregate flip rate, when the failure is a rate rather than a
            single case.
    """

    def __init__(
        self,
        message: str,
        *,
        perturbation: str | None = None,
        claim_id: str | None = None,
        original_verdict: str | None = None,
        perturbed_verdict: str | None = None,
        confidence_delta: float | None = None,
        flip_rate: float | None = None,
        **context: Any,
    ) -> None:
        self.perturbation = perturbation
        self.claim_id = claim_id
        self.original_verdict = original_verdict
        self.perturbed_verdict = perturbed_verdict
        self.confidence_delta = confidence_delta
        self.flip_rate = flip_rate
        super().__init__(
            message,
            perturbation=perturbation,
            claim_id=claim_id,
            original_verdict=original_verdict,
            perturbed_verdict=perturbed_verdict,
            confidence_delta=confidence_delta,
            flip_rate=flip_rate,
            **context,
        )
