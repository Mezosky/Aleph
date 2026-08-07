"""A provider for OpenAI-compatible chat-completions endpoints.

Named for the model family Aleph is developed against, but the wire protocol is
the generic one: vLLM, SGLang, TGI's OpenAI shim, llama.cpp's server, Ollama's
compatibility layer and most hosted Qwen deployments all speak it. That is the
reason to target the protocol rather than a vendor SDK — the deployment can be a
laptop, a self-hosted GPU box or a managed endpoint without a line of Aleph
changing, and no analysis becomes contingent on one company's continued goodwill.

Nothing here happens at import time. The HTTP client is built on first use, so
importing :mod:`aleph.llm` in a test run, a CI lint job or a static export costs
no socket and needs no credential.

The credential is held in :class:`~aleph.core.config.Secret` and is revealed at
exactly one place: the construction of the ``Authorization`` header, immediately
before the request. It is never logged, never placed in an exception context,
never returned by the API and never rendered by ``repr``.

Structured output is requested through the strongest mechanism the endpoint
supports and degrades explicitly, never silently: ``json_schema`` (decoder-
enforced) → ``json_object`` (parse-guaranteed) → prompt-only. Which one was used
is recorded on every response, because a schema-conforming answer that was
merely *asked for* deserves less trust than one that was structurally
guaranteed, and erasing that difference would overstate what the pipeline knows.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit

import httpx

from aleph.core.config import Config, Secret, get_config
from aleph.core.errors import ProviderError
from aleph.llm.base import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    FinishReason,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    RetryPolicy,
    StructuredOutputMode,
    TokenUsage,
    redact_url,
)

__all__ = ["QwenProvider", "STRUCTURED_OUTPUT_FALLBACK_ORDER"]

#: How structured output is attempted, strongest guarantee first. A 400 that
#: names ``response_format`` moves to the next entry and the downgrade is
#: recorded on the response rather than hidden.
STRUCTURED_OUTPUT_FALLBACK_ORDER: Final[tuple[StructuredOutputMode, ...]] = (
    StructuredOutputMode.JSON_SCHEMA,
    StructuredOutputMode.JSON_OBJECT,
    StructuredOutputMode.PROMPT,
)

_RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

_FINISH_REASONS: Final[dict[str, FinishReason]] = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "max_tokens": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
    "tool_calls": FinishReason.TOOL_CALLS,
    "function_call": FinishReason.TOOL_CALLS,
}


class QwenProvider(LLMProvider):
    """Talks to an OpenAI-compatible ``/chat/completions`` endpoint.

    Args:
        base_url: Endpoint root. When it has no path, ``/v1`` is appended,
            because that is where every implementation of this protocol puts
            the routes; an explicit path is left exactly as given.
        api_key: Credential. Accepts a :class:`~aleph.core.config.Secret` or a
            plain string, which is wrapped immediately so it cannot be logged
            by accident downstream.
        model: Model identifier sent in the request body.
        client / async_client: Pre-built httpx clients. The seam tests use to
            exercise this provider with a ``MockTransport`` and no network.
    """

    name = "qwen"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: Secret | str | None = None,
        model: str = "qwen2.5-72b-instruct",
        temperature: float = 0.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        retry: RetryPolicy | None = None,
        structured_output_mode: StructuredOutputMode = StructuredOutputMode.JSON_SCHEMA,
        extra_headers: Mapping[str, str] | None = None,
        client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            retry=retry,
        )
        if not base_url or not base_url.strip():
            raise ProviderError(
                "QwenProvider requires a base URL; set ALEPH_QWEN_BASE_URL or pass "
                "base_url explicitly, or use the deterministic 'mock' provider",
                provider=self.name,
                operation="configure",
                retryable=False,
            )
        self.base_url = _normalise_base_url(base_url)
        self.api_key = api_key if isinstance(api_key, Secret) else Secret(api_key)
        self.structured_output_mode = structured_output_mode
        self._extra_headers = dict(extra_headers or {})
        self._client = client
        self._async_client = async_client
        self._owns_client = client is None
        self._owns_async_client = async_client is None
        #: Set once the endpoint has rejected a stronger structured-output mode,
        #: so the downgrade is paid for once per process rather than per call.
        self._negotiated_mode: StructuredOutputMode | None = None

    # -- construction -------------------------------------------------------

    @classmethod
    def from_config(cls, config: Config | None = None, **overrides: Any) -> QwenProvider:
        """Build from ``ALEPH_QWEN_*`` settings.

        Raises:
            ProviderError: ``ALEPH_QWEN_BASE_URL`` is unset. Refusing here is
                deliberate: falling back to the mock would let a run that was
                meant to use a real model produce canned output that looks
                exactly like a real analysis.
        """
        cfg = config or get_config()
        kwargs: dict[str, Any] = {
            "base_url": cfg.qwen_base_url,
            "api_key": cfg.qwen_api_key,
            "model": cfg.qwen_model,
            "temperature": cfg.llm_temperature,
            "retry": RetryPolicy(max_attempts=max(1, cfg.llm_max_retries)),
            "timeout": cfg.request_timeout if cfg.request_timeout > 0 else DEFAULT_TIMEOUT_SECONDS,
        }
        kwargs.update(overrides)
        if not kwargs.get("base_url"):
            raise ProviderError(
                "provider 'qwen' is selected but ALEPH_QWEN_BASE_URL is not set. "
                "Set it to your OpenAI-compatible endpoint, or set "
                "ALEPH_LLM_PROVIDER=mock to run fully offline.",
                provider="qwen",
                operation="configure",
                retryable=False,
            )
        return cls(**kwargs)

    # -- transport ----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        """Build request headers. The only place the credential is revealed."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        headers.update(self._extra_headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key.reveal()}"
        return headers

    def _endpoint(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    @property
    def client(self) -> httpx.Client:
        """Lazily-built synchronous client. No socket is opened at import."""
        if self._client is None:
            self._client = httpx.Client(timeout=self.default_timeout)
        return self._client

    @property
    def async_client(self) -> httpx.AsyncClient:
        """Lazily-built asynchronous client."""
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self.default_timeout)
        return self._async_client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    async def aclose(self) -> None:
        if self._async_client is not None and self._owns_async_client:
            await self._async_client.aclose()
            self._async_client = None
        self.close()

    # -- one attempt --------------------------------------------------------

    def _invoke(self, request: LLMRequest) -> LLMResponse:
        for mode in self._modes_to_try(request):
            body = self._body(request, mode)
            started = time.perf_counter()
            try:
                raw = self.client.post(
                    self._endpoint("chat/completions"),
                    json=body,
                    headers=self._headers(),
                    timeout=request.timeout,
                )
            except httpx.TimeoutException as exc:
                raise self._transport_error(exc, "complete", retryable=True) from exc
            except httpx.HTTPError as exc:
                raise self._transport_error(exc, "complete", retryable=True) from exc
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            downgrade = self._downgrade_reason(raw, mode)
            if downgrade is not None:
                self._negotiated_mode = _next_mode(mode)
                continue
            self._raise_for_status(raw, "complete")
            return self._parse_completion(raw, mode, elapsed_ms)
        raise ProviderError(
            "endpoint rejected every structured-output mode, including plain prompting",
            provider=self.name,
            operation="complete",
            retryable=False,
            endpoint=redact_url(self.base_url),
        )

    async def _ainvoke(self, request: LLMRequest) -> LLMResponse:
        for mode in self._modes_to_try(request):
            body = self._body(request, mode)
            started = time.perf_counter()
            try:
                raw = await self.async_client.post(
                    self._endpoint("chat/completions"),
                    json=body,
                    headers=self._headers(),
                    timeout=request.timeout,
                )
            except httpx.TimeoutException as exc:
                raise self._transport_error(exc, "complete", retryable=True) from exc
            except httpx.HTTPError as exc:
                raise self._transport_error(exc, "complete", retryable=True) from exc
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            downgrade = self._downgrade_reason(raw, mode)
            if downgrade is not None:
                self._negotiated_mode = _next_mode(mode)
                continue
            self._raise_for_status(raw, "complete")
            return self._parse_completion(raw, mode, elapsed_ms)
        raise ProviderError(
            "endpoint rejected every structured-output mode, including plain prompting",
            provider=self.name,
            operation="complete",
            retryable=False,
            endpoint=redact_url(self.base_url),
        )

    # -- embeddings ---------------------------------------------------------

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Call ``/embeddings``. Optional everywhere it is used.

        Embeddings support clustering and near-duplicate detection. They never
        stand in for evidence: an assertion Aleph publishes must be traceable to
        a passage a reader can open, and cosine proximity is not a passage.
        """
        items = list(texts)
        if not items:
            return []
        try:
            raw = self.client.post(
                self._endpoint("embeddings"),
                json={"model": self.model_id, "input": items},
                headers=self._headers(),
                timeout=self.default_timeout,
            )
        except httpx.HTTPError as exc:
            raise self._transport_error(exc, "embed", retryable=True) from exc
        self._raise_for_status(raw, "embed")
        payload = _json_body(raw, self.name, "embed")
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(items):
            raise ProviderError(
                "embeddings response did not return one vector per input",
                provider=self.name,
                operation="embed",
                retryable=False,
                expected=len(items),
                received=len(data) if isinstance(data, list) else 0,
            )
        ordered = sorted(data, key=lambda row: int(row.get("index", 0)))
        return [[float(v) for v in row.get("embedding", ())] for row in ordered]

    async def aembed(self, texts: Sequence[str]) -> list[list[float]]:
        items = list(texts)
        if not items:
            return []
        try:
            raw = await self.async_client.post(
                self._endpoint("embeddings"),
                json={"model": self.model_id, "input": items},
                headers=self._headers(),
                timeout=self.default_timeout,
            )
        except httpx.HTTPError as exc:
            raise self._transport_error(exc, "embed", retryable=True) from exc
        self._raise_for_status(raw, "embed")
        payload = _json_body(raw, self.name, "embed")
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(items):
            raise ProviderError(
                "embeddings response did not return one vector per input",
                provider=self.name,
                operation="embed",
                retryable=False,
            )
        ordered = sorted(data, key=lambda row: int(row.get("index", 0)))
        return [[float(v) for v in row.get("embedding", ())] for row in ordered]

    # -- request/response shaping ------------------------------------------

    def _modes_to_try(self, request: LLMRequest) -> tuple[StructuredOutputMode, ...]:
        if request.schema is None:
            return (StructuredOutputMode.NONE,)
        start = self._negotiated_mode or self.structured_output_mode
        if start not in STRUCTURED_OUTPUT_FALLBACK_ORDER:
            return (StructuredOutputMode.PROMPT,)
        index = STRUCTURED_OUTPUT_FALLBACK_ORDER.index(start)
        return STRUCTURED_OUTPUT_FALLBACK_ORDER[index:]

    def _body(self, request: LLMRequest, mode: StructuredOutputMode) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        body: dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        if request.stop:
            body["stop"] = list(request.stop)
        if request.seed is not None:
            body["seed"] = request.seed
        if request.schema is None:
            return body

        if mode is StructuredOutputMode.JSON_SCHEMA:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "aleph_response",
                    "schema": dict(request.schema),
                    "strict": True,
                },
            }
        elif mode is StructuredOutputMode.JSON_OBJECT:
            body["response_format"] = {"type": "json_object"}
        # StructuredOutputMode.PROMPT sends nothing extra: the schema is already
        # in the system prompt and Aleph's own validation is the only guard.
        return body

    @staticmethod
    def _downgrade_reason(raw: httpx.Response, mode: StructuredOutputMode) -> str | None:
        """Whether this 4xx means "I do not support that structured-output mode".

        Restricted to 400/404/422 mentioning the field, so a genuine bad request
        is never mistaken for a capability gap and retried into a weaker mode
        that silently loses the schema guarantee.
        """
        if mode is StructuredOutputMode.PROMPT or mode is StructuredOutputMode.NONE:
            return None
        if raw.status_code not in (400, 404, 422):
            return None
        text = raw.text.lower()
        markers = ("response_format", "json_schema", "guided", "structured output")
        if any(marker in text for marker in markers):
            return f"endpoint rejected {mode.value} structured output"
        return None

    def _parse_completion(
        self, raw: httpx.Response, mode: StructuredOutputMode, elapsed_ms: float
    ) -> LLMResponse:
        payload = _json_body(raw, self.name, "complete")
        choices = payload.get("choices") or []
        if not choices:
            raise ProviderError(
                "chat-completions response contained no choices",
                provider=self.name,
                operation="complete",
                retryable=True,
                status_code=raw.status_code,
            )
        choice = choices[0]
        message = choice.get("message") or {}
        text = message.get("content")
        if text is None:
            text = ""
        usage_block = payload.get("usage") or {}
        usage = TokenUsage(
            prompt_tokens=int(usage_block.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_block.get("completion_tokens", 0) or 0),
        )
        finish = _FINISH_REASONS.get(str(choice.get("finish_reason", "")), FinishReason.UNKNOWN)
        return LLMResponse(
            text=str(text),
            model=str(payload.get("model") or self.model_id),
            provider=self.name,
            usage=usage,
            latency_ms=elapsed_ms,
            finish_reason=finish,
            structured_output_mode=mode,
        )

    # -- failures -----------------------------------------------------------

    def _raise_for_status(self, raw: httpx.Response, operation: str) -> None:
        if raw.status_code < 400:
            return
        detail = _safe_detail(raw)
        raise ProviderError(
            f"endpoint returned HTTP {raw.status_code}",
            provider=self.name,
            operation=operation,
            status_code=raw.status_code,
            retryable=raw.status_code in _RETRYABLE_STATUS,
            detail=detail,
            endpoint=redact_url(self.base_url),
        )

    def _transport_error(self, exc: Exception, operation: str, *, retryable: bool) -> ProviderError:
        """Wrap a transport failure, keeping the URL out of the message.

        ``httpx`` puts the full request URL in its exception text, and a base
        URL can carry a token in its query string, so only the exception type is
        propagated.
        """
        return ProviderError(
            f"transport failure contacting the model endpoint ({type(exc).__name__})",
            provider=self.name,
            operation=operation,
            retryable=retryable,
            endpoint=redact_url(self.base_url),
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _normalise_base_url(base_url: str) -> str:
    """Trim the trailing slash and add ``/v1`` when the URL carries no path.

    ``https://host`` becomes ``https://host/v1``; ``https://host/openai/v1`` and
    ``https://host/v1`` are left alone. Guessing further would be worse than
    failing: a wrong path produces a 404 an operator can read.

    Reassembled through ``urlunsplit`` rather than string concatenation, so a
    base URL carrying a query string (some gateways put a token there) gets the
    path inserted in the right place instead of ``/v1`` being glued onto the end
    of the query.
    """
    trimmed = base_url.strip().rstrip("/")
    parts = urlsplit(trimmed)
    if not parts.scheme or parts.path:
        return trimmed
    return urlunsplit((parts.scheme, parts.netloc, "/v1", parts.query, parts.fragment))


def _next_mode(mode: StructuredOutputMode) -> StructuredOutputMode:
    if mode not in STRUCTURED_OUTPUT_FALLBACK_ORDER:
        return StructuredOutputMode.PROMPT
    index = STRUCTURED_OUTPUT_FALLBACK_ORDER.index(mode)
    if index + 1 >= len(STRUCTURED_OUTPUT_FALLBACK_ORDER):
        return StructuredOutputMode.PROMPT
    return STRUCTURED_OUTPUT_FALLBACK_ORDER[index + 1]


def _json_body(raw: httpx.Response, provider: str, operation: str) -> dict[str, Any]:
    try:
        payload = raw.json()
    except ValueError as exc:
        raise ProviderError(
            "endpoint returned a non-JSON body",
            provider=provider,
            operation=operation,
            status_code=raw.status_code,
            retryable=True,
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderError(
            "endpoint returned a JSON value that was not an object",
            provider=provider,
            operation=operation,
            status_code=raw.status_code,
            retryable=False,
        )
    return payload


def _safe_detail(raw: httpx.Response, limit: int = 400) -> str:
    """Extract a short provider-side message, truncated and credential-free.

    Only the ``error.message`` field is read where present. A whole error body
    is not echoed: some gateways reflect request headers back on failure, and
    that would put the ``Authorization`` header into a log.
    """
    try:
        payload = raw.json()
    except ValueError:
        return raw.text[:limit].replace("\n", " ").strip()
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message[:limit]
        if isinstance(error, str):
            return error[:limit]
        message = payload.get("message")
        if isinstance(message, str):
            return message[:limit]
    return ""
