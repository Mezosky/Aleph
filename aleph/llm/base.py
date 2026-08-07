"""The vendor boundary: everything Aleph is allowed to ask a language model for.

Aleph makes a promise it can only keep if the model layer is a *narrow* seam:
that a verdict is a function of the claim and the evidence, and of nothing else.
A pipeline wired directly to one vendor's SDK cannot keep that promise, because
the vendor's affordances — a bespoke "judge" endpoint, a hosted reranker, a
built-in web search — quietly become part of the reasoning, and swapping the
model would then swap the epistemics too.

So this module defines the whole surface: a model can complete a prompt, and it
may optionally embed text. That is all. Everything Aleph concludes is assembled
by Aleph's own code out of those two primitives, from inputs Aleph constructed
and can show you.

**Swapping the provider must leave the factual evaluation pipeline unchanged.**
That is the design constraint this abstraction exists to protect, and it is
testable rather than aspirational: :class:`~aleph.llm.mock.MockProvider` runs
the entire pipeline offline, and any provider that produces schema-valid
completions must produce a bundle with the same *shape*, the same checks and the
same inspectability. A provider that needed extra input, or that returned a
verdict Aleph did not derive, would be a provider Aleph cannot use.

Three concerns are handled here once, rather than in each provider:

* **Retry with backoff.** Transient infrastructure failure is Aleph's problem,
  not a finding about the evidence. Retries are bounded and deterministic (no
  random jitter), so a run stays reproducible.
* **Timeouts.** A hung request must fail loudly rather than stall a phase.
* **Structured-output enforcement.** When a caller supplies a JSON Schema, the
  response is parsed and validated against it, and a mismatch is *retried with
  the validation error fed back* before it is allowed to fail. Downstream code
  therefore never has to defend itself against a model that returned prose where
  an object was required — a defence that, done ad hoc, degrades into guessing
  what the model meant, which is precisely how unfounded content enters an
  analysis.

Credentials never appear in a ``repr``, a log line, an exception or an error
context: :class:`~aleph.core.config.Secret` refuses to render, and
:meth:`LLMProvider.__repr__` shows only the host of an endpoint.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Final
from urllib.parse import urlsplit

from aleph.core.config import REDACTED, Config, Secret
from aleph.core.errors import ProviderError, SchemaMismatchError

__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TIMEOUT_SECONDS",
    "FinishReason",
    "JSON_INSTRUCTION",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "RetryPolicy",
    "StructuredOutputMode",
    "TokenUsage",
    "coerce_json",
    "describe_schema_errors",
    "redact_url",
    "validate_against_schema",
]

#: Default ceiling on a single completion. Generous enough for a full document
#: section, small enough that a runaway generation fails fast.
DEFAULT_MAX_TOKENS: Final[int] = 2048

#: Default per-request wall-clock budget, in seconds.
DEFAULT_TIMEOUT_SECONDS: Final[float] = 120.0

#: Appended to a system prompt when a schema is supplied. Kept in one place so
#: every provider asks for structure in the same words, and a change in phrasing
#: is a change to one constant rather than a drift between vendors.
JSON_INSTRUCTION: Final[str] = (
    "Respond with a single JSON value that validates against the supplied JSON "
    "Schema. Output the JSON and nothing else: no prose before or after it, no "
    "markdown code fence, no explanation. If you cannot determine a value from "
    "the input, use the schema's null or empty form rather than inventing one."
)


class FinishReason(StrEnum):
    """Why generation stopped.

    ``length`` is not a benign detail: a completion truncated mid-object is the
    commonest way a structurally valid but *semantically amputated* result
    reaches a pipeline, so callers must be able to see it and downstream schema
    validation must be able to reject it.
    """

    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    TOOL_CALLS = "tool_calls"
    ERROR = "error"
    UNKNOWN = "unknown"


class StructuredOutputMode(StrEnum):
    """How a provider was asked to constrain its output to a schema.

    Recorded on the response because the three modes carry different guarantees.
    ``json_schema`` is enforced by the server's decoder and cannot produce an
    invalid shape; ``json_object`` guarantees only that the output parses;
    ``prompt`` guarantees nothing and relies entirely on Aleph's own validation
    and retry. A result obtained under ``prompt`` deserves less trust than the
    same result obtained under ``json_schema``, and hiding which one happened
    would erase that distinction.
    """

    NONE = "none"
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPT = "prompt"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Tokens consumed by one call.

    Carried because cost and truncation risk are operational facts a maintainer
    needs, and because a phase whose prompts have quietly doubled in size is
    usually a phase whose inputs have gone wrong.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )

    def to_jsonable(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded, deterministic retry.

    There is no random jitter. Jitter spreads load across many clients, and Aleph
    is one client running a reproducible analysis; randomness here would buy
    nothing and cost the property that two runs over the same document behave
    the same way. Backoff is capped so a failing endpoint costs a bounded amount
    of wall clock before the phase is honestly marked failed.
    """

    max_attempts: int = 3
    initial_backoff: float = 0.5
    multiplier: float = 2.0
    max_backoff: float = 8.0

    def backoff_for(self, attempt: int) -> float:
        """Seconds to wait before attempt ``attempt`` (1-based, so 1 waits 0)."""
        if attempt <= 1:
            return 0.0
        delay = self.initial_backoff * (self.multiplier ** (attempt - 2))
        return float(min(delay, self.max_backoff))


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """One completion request, fully described.

    Frozen and self-contained so it can be hashed, logged, replayed and diffed.
    :class:`~aleph.llm.mock.MockProvider` keys its deterministic responses off
    exactly this object, which is what makes an offline run reproducible down to
    the byte.
    """

    prompt: str
    system: str | None = None
    schema: Mapping[str, Any] | None = None
    temperature: float = 0.0
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    stop: tuple[str, ...] = ()
    seed: int | None = None
    purpose: str | None = None
    """Free-form label naming the pipeline step, e.g. ``'proposition_extraction'``.
    Recorded so a bad output can be traced to the step that asked for it."""

    def fingerprint(self) -> str:
        """A stable content hash of everything that could change the answer."""
        from aleph.core.ids import stable_hash

        return stable_hash(
            self.prompt,
            self.system or "",
            _canonical_json(self.schema) if self.schema is not None else "",
            f"{self.temperature:.6f}",
            self.max_tokens,
            "|".join(self.stop),
            self.seed if self.seed is not None else "",
        )


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """What a provider returned, and everything needed to audit it.

    ``parsed`` is populated only when a schema was supplied *and* the payload
    validated against it. A response with a schema and ``parsed is None`` is a
    failure that was allowed through deliberately (``strict=False``); it is never
    a silent partial success, and :attr:`schema_valid` records which happened.
    """

    text: str
    model: str
    provider: str
    parsed: Any | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: float = 0.0
    finish_reason: FinishReason = FinishReason.UNKNOWN
    attempts: int = 1
    schema_valid: bool | None = None
    """``None`` when no schema was requested; otherwise whether it validated."""
    structured_output_mode: StructuredOutputMode = StructuredOutputMode.NONE
    validation_errors: tuple[str, ...] = ()
    request_fingerprint: str | None = None

    @property
    def truncated(self) -> bool:
        """Whether generation was cut off by the token ceiling."""
        return self.finish_reason is FinishReason.LENGTH

    def to_jsonable(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping for a run log.

        The completion text is included; no credential can reach here, because
        no provider puts one in a response object.
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "text": self.text,
            "parsed": self.parsed,
            "usage": self.usage.to_jsonable(),
            "latency_ms": round(self.latency_ms, 3),
            "finish_reason": self.finish_reason.value,
            "attempts": self.attempts,
            "schema_valid": self.schema_valid,
            "structured_output_mode": self.structured_output_mode.value,
            "validation_errors": list(self.validation_errors),
            "request_fingerprint": self.request_fingerprint,
        }


# ---------------------------------------------------------------------------
# JSON coercion and schema validation
# ---------------------------------------------------------------------------

_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"```(?:json|JSON)?\s*(?P<body>.*?)```", re.DOTALL)


def _canonical_json(value: Any) -> str:
    """Deterministic JSON rendering, used for hashing and for prompts."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def coerce_json(text: str) -> Any | None:
    """Recover a JSON value from a completion, or ``None`` if there is none.

    Models wrap JSON in code fences, prefix it with "Here is the JSON:", and
    append commentary. Recovering the value is legitimate; *guessing* at a value
    the model did not produce is not, so this function only ever extracts a
    literal substring and parses it. It never repairs, never fills in missing
    keys, and returns ``None`` rather than something plausible.
    """
    candidate = text.strip()
    if not candidate:
        return None

    for attempt in _json_candidates(candidate):
        try:
            return json.loads(attempt)
        except (ValueError, TypeError):
            continue
    return None


def _json_candidates(text: str) -> list[str]:
    """Substrings of ``text`` that might be a JSON value, best guess first."""
    candidates: list[str] = [text]

    fenced = _FENCE_RE.search(text)
    if fenced is not None:
        candidates.append(fenced.group("body").strip())

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])

    seen: set[str] = set()
    unique: list[str] = []
    for item in candidates:
        stripped = item.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            unique.append(stripped)
    return unique


def describe_schema_errors(payload: Any, schema: Mapping[str, Any]) -> tuple[str, ...]:
    """Return human-readable validation errors, empty when the payload is valid.

    Uses ``jsonschema`` when it is importable and degrades to a minimal
    structural check when it is not. The degraded path checks type, required
    keys and enum membership only, and says so: a weaker check that pretended to
    be a full one would let malformed model output into a bundle under the
    appearance of validation.
    """
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - jsonschema is a declared dependency
        return _minimal_schema_errors(payload, schema)

    validator_cls = jsonschema.validators.validator_for(dict(schema))
    validator = validator_cls(dict(schema))
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.absolute_path))
    out: list[str] = []
    for err in errors[:12]:
        path = "/".join(str(part) for part in err.absolute_path) or "<root>"
        out.append(f"{path}: {err.message}")
    return tuple(out)


def _minimal_schema_errors(payload: Any, schema: Mapping[str, Any]) -> tuple[str, ...]:
    """Fallback structural check. Deliberately shallow, and labelled as such."""
    errors: list[str] = []
    expected = schema.get("type")
    type_map: dict[str, type | tuple[type, ...]] = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    if isinstance(expected, str) and expected in type_map:
        python_type = type_map[expected]
        if expected == "integer" and isinstance(payload, bool):
            errors.append("<root>: expected integer, got boolean")
        elif not isinstance(payload, python_type):
            errors.append(f"<root>: expected {expected}, got {type(payload).__name__}")
    if isinstance(payload, dict):
        for key in schema.get("required", ()) or ():
            if key not in payload:
                errors.append(f"<root>: missing required property {key!r}")
    enum = schema.get("enum")
    if enum is not None and payload not in enum:
        errors.append(f"<root>: {payload!r} is not one of the permitted values")
    if errors:
        errors.append("(shallow check only: jsonschema unavailable)")
    return tuple(errors)


def validate_against_schema(payload: Any, schema: Mapping[str, Any], *, what: str) -> None:
    """Raise :class:`~aleph.core.errors.SchemaMismatchError` if invalid."""
    errors = describe_schema_errors(payload, schema)
    if errors:
        raise SchemaMismatchError(
            f"{what}: model output did not validate against the requested schema",
            errors=list(errors),
        )


def redact_url(url: str) -> str:
    """Render an endpoint as scheme + host, dropping any embedded credential.

    Base URLs occasionally carry a token in the userinfo or the query string.
    Every place Aleph displays an endpoint goes through here, so a credential
    cannot reach a log line by way of a URL.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:  # pragma: no cover - urlsplit is very permissive
        return REDACTED
    if not parts.scheme and not parts.netloc:
        return url.split("?", 1)[0]
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    credential_marker = "@" if parts.username or parts.password else ""
    return f"{parts.scheme}://{credential_marker}{host}{port}{parts.path}".rstrip("/")


# ---------------------------------------------------------------------------
# The provider abstraction
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """The only way Aleph talks to a language model.

    Subclasses implement two narrow hooks — :meth:`_invoke` and
    :meth:`_ainvoke` — which perform exactly one attempt and return an
    :class:`LLMResponse` with ``parsed`` left unset. Everything above them
    (retry, backoff, timeout accounting, JSON recovery, schema validation,
    validation-feedback retry) is implemented once here, so no provider can
    accidentally ship weaker guarantees than another and a comparison between
    two models stays a comparison between two models.

    Subclasses must also set :attr:`name` and :attr:`model_id`, and may override
    :meth:`embed`. Embeddings are optional by design: nothing in the factual
    path depends on them, so a deployment with no embedding endpoint loses a
    convenience, never a verdict.
    """

    #: Short provider identifier, e.g. ``'qwen'``, ``'mock'``.
    name: str = "provider"

    def __init__(
        self,
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.model_id = model
        self.default_temperature = temperature
        self.default_max_tokens = max_tokens
        self.default_timeout = timeout
        self.retry = retry or RetryPolicy()
        self._sleep = sleep if sleep is not None else time.sleep

    # -- construction -------------------------------------------------------

    @classmethod
    def from_config(cls, config: Config | None = None, **overrides: Any) -> LLMProvider:
        """Build the provider from Aleph's frozen configuration.

        Subclasses override this. The base implementation exists so callers can
        write ``type(p).from_config(cfg)`` uniformly.
        """
        raise NotImplementedError(
            f"{cls.__name__} does not implement from_config(); construct it directly"
        )

    # -- the two hooks a provider must implement ----------------------------

    @abstractmethod
    def _invoke(self, request: LLMRequest) -> LLMResponse:
        """Perform exactly one completion attempt, synchronously.

        Implementations must raise :class:`~aleph.core.errors.ProviderError`
        with ``retryable`` set truthfully on failure, and must not retry: retry
        policy belongs to the base class so it is uniform across vendors.
        """

    @abstractmethod
    async def _ainvoke(self, request: LLMRequest) -> LLMResponse:
        """Perform exactly one completion attempt, asynchronously."""

    # -- the public surface -------------------------------------------------

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema: Mapping[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        stop: Sequence[str] = (),
        seed: int | None = None,
        purpose: str | None = None,
        strict: bool = True,
    ) -> LLMResponse:
        """Complete ``prompt``, enforcing ``schema`` when one is given.

        Args:
            prompt: The user-role content.
            system: System-role content. The JSON instruction is appended
                automatically when a schema is supplied.
            schema: JSON Schema the response must validate against. When set,
                the response is parsed, validated, and — on mismatch — retried
                with the validation errors fed back to the model.
            temperature: Overrides the provider default. Aleph's default is 0.
            max_tokens: Overrides the provider default.
            timeout: Per-attempt wall-clock budget in seconds.
            stop: Stop sequences.
            seed: Sampling seed, where the endpoint honours one.
            purpose: Label for the pipeline step making the call, recorded so a
                suspect output can be traced back to what asked for it.
            strict: When ``True`` (the default) a response that still fails
                validation after all retries raises
                :class:`~aleph.core.errors.SchemaMismatchError`. When ``False``
                the response is returned with ``parsed=None``,
                ``schema_valid=False`` and the errors attached — for callers
                that have a documented fallback and would rather degrade than
                fail the phase.

        Returns:
            The completion, with ``parsed`` set when a schema was supplied and
            satisfied.

        Raises:
            ProviderError: The endpoint failed and retries were exhausted.
            SchemaMismatchError: ``strict`` and the output never validated.
        """
        request = self._build_request(
            prompt,
            system=system,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            stop=stop,
            seed=seed,
            purpose=purpose,
        )
        return self._run_with_retries(request, strict=strict)

    async def acomplete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema: Mapping[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        stop: Sequence[str] = (),
        seed: int | None = None,
        purpose: str | None = None,
        strict: bool = True,
    ) -> LLMResponse:
        """Asynchronous twin of :meth:`complete`, with identical semantics.

        Identical is the point: an async pipeline and a sync one must not be
        able to produce different analyses of the same document.
        """
        request = self._build_request(
            prompt,
            system=system,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            stop=stop,
            seed=seed,
            purpose=purpose,
        )
        return await self._arun_with_retries(request, strict=strict)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one dense vector per input text.

        Optional. The default raises :class:`NotImplementedError`, and callers
        must treat embeddings as a convenience for clustering and deduplication
        — never as an input to a factual verdict, which is derived from evidence
        that a reader can open and read.
        """
        raise NotImplementedError(f"{type(self).__name__} does not provide embeddings")

    async def aembed(self, texts: Sequence[str]) -> list[list[float]]:
        """Asynchronous twin of :meth:`embed`."""
        return await asyncio.to_thread(self.embed, list(texts))

    def close(self) -> None:  # noqa: B027 - optional hook, not an abstract method
        """Release any transport resources. Safe to call more than once.

        Deliberately concrete and empty rather than abstract: a provider with no
        transport (the mock) has nothing to release, and forcing it to implement
        an empty override would be ceremony.
        """

    async def aclose(self) -> None:
        """Asynchronous twin of :meth:`close`."""
        self.close()

    def __enter__(self) -> LLMProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    async def __aenter__(self) -> LLMProvider:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # -- introspection ------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """A credential-free description, safe to embed in a bundle's methodology.

        A reader is entitled to know which model judged these claims, and that
        entitlement stops precisely at the credential used to reach it.
        """
        return {
            "provider": self.name,
            "model": self.model_id,
            "temperature": self.default_temperature,
            "max_tokens": self.default_max_tokens,
            "deterministic": self.is_deterministic,
        }

    @property
    def is_deterministic(self) -> bool:
        """Whether repeated identical requests are guaranteed identical answers.

        Only the mock can promise this. A hosted endpoint at temperature 0 is
        usually stable and never guaranteed, and overstating that would let a
        result that moved between runs be reported as reproducible.
        """
        return False

    def __repr__(self) -> str:
        """Redacted by construction — never renders a key or a URL credential."""
        parts = [f"model={self.model_id!r}", f"temperature={self.default_temperature!r}"]
        endpoint = getattr(self, "base_url", None)
        if endpoint:
            parts.insert(0, f"endpoint={redact_url(str(endpoint))!r}")
        key = getattr(self, "api_key", None)
        if isinstance(key, Secret):
            parts.append(f"api_key={'set' if key else 'unset'}({REDACTED})")
        elif key is not None:
            parts.append(f"api_key={REDACTED}")
        return f"{type(self).__name__}({', '.join(parts)})"

    # -- internals ----------------------------------------------------------

    def _build_request(
        self,
        prompt: str,
        *,
        system: str | None,
        schema: Mapping[str, Any] | None,
        temperature: float | None,
        max_tokens: int | None,
        timeout: float | None,
        stop: Sequence[str],
        seed: int | None,
        purpose: str | None,
    ) -> LLMRequest:
        if not prompt or not prompt.strip():
            raise ValueError("prompt must not be empty")
        return LLMRequest(
            prompt=prompt,
            system=self._compose_system(system, schema),
            schema=dict(schema) if schema is not None else None,
            temperature=(self.default_temperature if temperature is None else float(temperature)),
            max_tokens=int(max_tokens) if max_tokens is not None else self.default_max_tokens,
            timeout=float(timeout) if timeout is not None else self.default_timeout,
            stop=tuple(stop),
            seed=seed,
            purpose=purpose,
        )

    @staticmethod
    def _compose_system(system: str | None, schema: Mapping[str, Any] | None) -> str | None:
        """Attach the JSON instruction and the schema text to the system prompt.

        The schema is included in the prompt even when the endpoint enforces it
        server-side: a model told what shape is wanted produces better *content*
        inside a shape it was going to be forced into anyway.
        """
        if schema is None:
            return system
        blocks = [system.strip()] if system and system.strip() else []
        blocks.append(JSON_INSTRUCTION)
        blocks.append("JSON Schema:\n" + json.dumps(dict(schema), indent=2, ensure_ascii=False))
        return "\n\n".join(blocks)

    def _run_with_retries(self, request: LLMRequest, *, strict: bool) -> LLMResponse:
        attempts = 0
        last_error: ProviderError | None = None
        current = request
        validation_errors: tuple[str, ...] = ()
        last_response: LLMResponse | None = None

        for attempt in range(1, max(1, self.retry.max_attempts) + 1):
            delay = self.retry.backoff_for(attempt)
            if delay:
                self._sleep(delay)
            attempts = attempt
            started = time.perf_counter()
            try:
                response = self._invoke(current)
            except ProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self.retry.max_attempts:
                    raise
                continue
            response = self._stamp(response, request, attempts, started)
            if request.schema is None:
                return response
            checked, validation_errors = self._apply_schema(response, request.schema)
            if checked.schema_valid:
                return checked
            last_response = checked
            if attempt < self.retry.max_attempts:
                current = self._with_repair_hint(current, validation_errors)
        return self._finish_invalid(
            last_response, request, attempts, validation_errors, last_error, strict=strict
        )

    async def _arun_with_retries(self, request: LLMRequest, *, strict: bool) -> LLMResponse:
        attempts = 0
        last_error: ProviderError | None = None
        current = request
        validation_errors: tuple[str, ...] = ()
        last_response: LLMResponse | None = None

        for attempt in range(1, max(1, self.retry.max_attempts) + 1):
            delay = self.retry.backoff_for(attempt)
            if delay:
                await asyncio.sleep(delay)
            attempts = attempt
            started = time.perf_counter()
            try:
                response = await self._ainvoke(current)
            except ProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self.retry.max_attempts:
                    raise
                continue
            response = self._stamp(response, request, attempts, started)
            if request.schema is None:
                return response
            checked, validation_errors = self._apply_schema(response, request.schema)
            if checked.schema_valid:
                return checked
            last_response = checked
            if attempt < self.retry.max_attempts:
                current = self._with_repair_hint(current, validation_errors)
        return self._finish_invalid(
            last_response, request, attempts, validation_errors, last_error, strict=strict
        )

    def _stamp(
        self, response: LLMResponse, request: LLMRequest, attempts: int, started: float
    ) -> LLMResponse:
        """Attach timing, attempt count and the request fingerprint."""
        latency = response.latency_ms or (time.perf_counter() - started) * 1000.0
        return replace(
            response,
            attempts=attempts,
            latency_ms=latency,
            request_fingerprint=request.fingerprint(),
        )

    @staticmethod
    def _apply_schema(
        response: LLMResponse, schema: Mapping[str, Any]
    ) -> tuple[LLMResponse, tuple[str, ...]]:
        """Parse and validate; return the annotated response and any errors."""
        payload = response.parsed if response.parsed is not None else coerce_json(response.text)
        if payload is None:
            errors = ("<root>: response contained no parseable JSON value",)
            return (
                replace(response, parsed=None, schema_valid=False, validation_errors=errors),
                errors,
            )
        errors = describe_schema_errors(payload, schema)
        if errors:
            return (
                replace(response, parsed=None, schema_valid=False, validation_errors=errors),
                errors,
            )
        return replace(response, parsed=payload, schema_valid=True, validation_errors=()), ()

    @staticmethod
    def _with_repair_hint(request: LLMRequest, errors: Sequence[str]) -> LLMRequest:
        """Feed the validation errors back so the retry is informed, not blind.

        Retrying an identical prompt against a deterministic endpoint would
        reproduce the same invalid output; naming the specific failures is what
        makes the second attempt worth spending.
        """
        listed = "\n".join(f"- {err}" for err in errors[:12])
        return replace(
            request,
            prompt=(
                f"{request.prompt}\n\n"
                "The previous response did not validate against the required JSON "
                f"Schema. Fix exactly these problems and return the corrected JSON "
                f"only:\n{listed}"
            ),
        )

    def _finish_invalid(
        self,
        response: LLMResponse | None,
        request: LLMRequest,
        attempts: int,
        errors: Sequence[str],
        last_error: ProviderError | None,
        *,
        strict: bool,
    ) -> LLMResponse:
        if response is None:
            raise ProviderError(
                "provider returned no usable response after all attempts",
                provider=self.name,
                operation="complete",
                retryable=False,
                detail=str(last_error) if last_error is not None else None,
                purpose=request.purpose,
                attempts=attempts,
            )
        if strict:
            raise SchemaMismatchError(
                "model output never validated against the requested schema "
                f"after {attempts} attempt(s)",
                errors=list(errors),
                source=f"{self.name}:{self.model_id}",
                stage=request.purpose,
            )
        return response
