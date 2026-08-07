"""The model layer — the seam that keeps Aleph's conclusions Aleph's own.

Aleph asks a language model for two things and nothing else: complete this
prompt, and (optionally) embed this text. Every judgement in a published bundle
is assembled by Aleph's own code from inputs it constructed and can show a
reader. The abstraction exists to hold that line: **swapping the provider must
leave the factual evaluation pipeline unchanged.**

* :mod:`aleph.llm.base` — :class:`~aleph.llm.base.LLMProvider`, the ABC every
  caller codes against, with retry, timeout and schema enforcement implemented
  once so no backend can ship weaker guarantees than another.
* :mod:`aleph.llm.mock` — :class:`~aleph.llm.mock.MockProvider`, fully
  deterministic and offline, and the default. It synthesises schema-valid
  responses, so the whole pipeline, the tests and CI run with no credentials.
* :mod:`aleph.llm.qwen` — :class:`~aleph.llm.qwen.QwenProvider`, speaking the
  OpenAI-compatible chat-completions protocol that vLLM and most Qwen
  deployments expose. Imported lazily; nothing here opens a socket at import.
* :mod:`aleph.llm.registry` — :func:`~aleph.llm.registry.get_provider`,
  resolving from configuration, defaulting to the mock and refusing — never
  silently downgrading — when a requested provider is unconfigured.
"""

from __future__ import annotations

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
    coerce_json,
    describe_schema_errors,
    validate_against_schema,
)
from aleph.llm.mock import MOCK_MODEL_ID, MockProvider, synthesise_from_schema
from aleph.llm.registry import (
    DEFAULT_PROVIDER,
    available_providers,
    get_provider,
    provider_status,
    register_provider,
)

__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_PROVIDER",
    "DEFAULT_TIMEOUT_SECONDS",
    "MOCK_MODEL_ID",
    "FinishReason",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "MockProvider",
    "RetryPolicy",
    "StructuredOutputMode",
    "TokenUsage",
    "available_providers",
    "coerce_json",
    "describe_schema_errors",
    "get_provider",
    "provider_status",
    "register_provider",
    "synthesise_from_schema",
    "validate_against_schema",
]


def __getattr__(name: str) -> object:
    """Expose ``QwenProvider`` without importing httpx unless it is asked for."""
    if name == "QwenProvider":
        from aleph.llm.qwen import QwenProvider

        return QwenProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
