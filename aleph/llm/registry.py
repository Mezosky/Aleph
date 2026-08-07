"""Provider resolution: one place that decides which model Aleph is talking to.

Two rules drive this module, and both are about failure modes rather than
convenience.

**The safe default is the offline one.** With nothing configured, Aleph resolves
to :class:`~aleph.llm.mock.MockProvider`: deterministic, credential-free,
network-free. A default that reached for a hosted endpoint would mean a clone of
this repository could make outbound requests on a first ``pytest`` run, and
would make "it worked on my machine" depend on someone's API key.

**A requested provider that is not configured is an error, never a downgrade.**
If an operator asks for ``qwen`` and the endpoint is unset, this module raises.
It does not quietly fall back to the mock, because canned output is
indistinguishable from real output *in shape* — that is the whole point of the
mock — and a run that silently swapped a real model for synthetic filler would
produce a bundle that looks like an analysis and is not one. The one place that
distinction is recorded is a bundle's methodology block, and it must be true.

Resolution order for :func:`get_provider`: an explicit ``name`` argument, then
``ALEPH_LLM_PROVIDER``, then ``mock``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

from aleph.core.config import Config, get_config
from aleph.core.enums import LLMProviderName
from aleph.core.errors import ProviderError
from aleph.llm.base import LLMProvider
from aleph.llm.mock import MockProvider

__all__ = [
    "DEFAULT_PROVIDER",
    "ProviderFactory",
    "available_providers",
    "get_provider",
    "provider_status",
    "register_provider",
]

#: What you get when nothing asks for anything else.
DEFAULT_PROVIDER: Final[LLMProviderName] = LLMProviderName.MOCK

ProviderFactory = Callable[[Config, Mapping[str, Any]], LLMProvider]


def _build_mock(config: Config, overrides: Mapping[str, Any]) -> LLMProvider:
    return MockProvider.from_config(config, **dict(overrides))


def _build_qwen(config: Config, overrides: Mapping[str, Any]) -> LLMProvider:
    # Imported here, not at module scope, so that ``import aleph.llm`` in an
    # offline test run never pulls in the HTTP client stack.
    from aleph.llm.qwen import QwenProvider

    return QwenProvider.from_config(config, **dict(overrides))


_FACTORIES: dict[str, ProviderFactory] = {
    LLMProviderName.MOCK.value: _build_mock,
    LLMProviderName.QWEN.value: _build_qwen,
}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Add or replace a provider implementation.

    The extension point that keeps the vendor boundary honest: a new backend is
    a factory registered here, not an edit to the pipeline. Whatever it is, it
    receives the same :class:`~aleph.llm.base.LLMRequest` and must return the
    same :class:`~aleph.llm.base.LLMResponse`, so the factual evaluation path is
    unchanged by the swap.

    Args:
        name: Lowercase identifier used by ``ALEPH_LLM_PROVIDER``.
        factory: Callable taking ``(config, overrides)`` and returning a
            provider.
    """
    key = name.strip().lower()
    if not key:
        raise ValueError("provider name must not be empty")
    _FACTORIES[key] = factory


def available_providers() -> tuple[str, ...]:
    """Registered provider names, in a stable order."""
    return tuple(sorted(_FACTORIES))


def get_provider(
    name: str | LLMProviderName | None = None,
    *,
    config: Config | None = None,
    **overrides: Any,
) -> LLMProvider:
    """Resolve and construct a provider.

    Args:
        name: Explicit provider name. ``None`` reads ``ALEPH_LLM_PROVIDER`` from
            configuration, which itself defaults to ``mock``.
        config: Configuration snapshot to read. Defaults to the process-wide one.
        **overrides: Passed to the provider's ``from_config``, e.g. ``model=``,
            ``timeout=``, or an injected ``client=`` for tests.

    Returns:
        A ready provider. No network request is made during construction.

    Raises:
        ProviderError: The name is unknown, or the named provider is missing
            required configuration. Both are refusals rather than fallbacks: see
            the module docstring.
    """
    cfg = config or get_config()
    requested = name if name is not None else cfg.llm_provider
    key = (requested.value if isinstance(requested, LLMProviderName) else str(requested)).strip()
    key = key.lower()

    if not key:
        key = DEFAULT_PROVIDER.value

    factory = _FACTORIES.get(key)
    if factory is None:
        raise ProviderError(
            f"unknown LLM provider {key!r}",
            provider=key,
            operation="resolve",
            retryable=False,
            available=list(available_providers()),
            hint=(
                "set ALEPH_LLM_PROVIDER to one of the available names, or call "
                "aleph.llm.register_provider() to add your own"
            ),
        )
    return factory(cfg, overrides)


def provider_status(config: Config | None = None) -> dict[str, Any]:
    """Report which providers are usable, without constructing or contacting any.

    Safe to expose from a diagnostics endpoint: it reports only *whether* a
    credential is configured, never its value. Useful for answering "why did my
    run come out synthetic?" before a pipeline has been started.
    """
    cfg = config or get_config()
    selected = cfg.llm_provider.value
    return {
        "selected": selected,
        "default": DEFAULT_PROVIDER.value,
        "available": list(available_providers()),
        "mock": {
            "configured": True,
            "deterministic": True,
            "requires_credentials": False,
        },
        "qwen": {
            "configured": bool(cfg.qwen_base_url),
            "deterministic": False,
            "requires_credentials": False,
            "api_key_configured": bool(cfg.qwen_api_key),
            "model": cfg.qwen_model,
            "revision": cfg.qwen_revision,
        },
    }
