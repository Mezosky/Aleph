"""Runtime configuration, read once from the environment and then frozen.

Configuration is an epistemic surface in Aleph, not just plumbing. Three of the
settings here decide what an analysis is *allowed to do to the world and to
itself*, and getting them wrong silently would undermine results that look fine:

* ``retrieval_mode`` defaults to ``manual``, which forbids any outbound fetch as
  a side effect of a pipeline run. Network access must be a deliberate act, both
  so a run is reproducible against a fixed evidence set and so no source
  receives traffic nobody asked for.
* ``llm_provider`` defaults to ``mock``, a deterministic offline provider, so the
  whole pipeline runs end to end with no credentials and produces the same
  bundle every time. A non-deterministic provider is opt-in.
* ``seed`` fixes every stochastic step. Two analyses of the same text must be
  diffable; a result that moves because of sampling noise is not a finding.

The API key is wrapped in :class:`Secret`, whose ``repr`` and ``str`` are
redacted and which raises if anyone tries to serialise it. That is not
belt-and-braces: config objects get logged, echoed into error contexts, and
returned from debug endpoints, and a plain string would leak through any of
those paths.

Deliberately implemented with the standard library plus plain dataclasses rather
than ``pydantic-settings``: this module is imported by everything, must never
perform I/O beyond reading ``os.environ``, and must not add a dependency that the
API layer and the CLI would then both have to agree on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, TypeVar

from aleph.core.enums import LLMProviderName, RetrievalMode

__all__ = [
    "ENV_PREFIX",
    "REDACTED",
    "Secret",
    "Config",
    "get_config",
    "reset_config_cache",
    "load_config",
]

#: Every Aleph environment variable is namespaced, so a stray ``DATA_DIR`` in a
#: shared shell can never silently redirect an analysis.
ENV_PREFIX: Final[str] = "ALEPH_"

#: What a secret renders as, everywhere.
REDACTED: Final[str] = "***redacted***"

_TRUE = frozenset({"1", "true", "yes", "on", "y"})
_FALSE = frozenset({"0", "false", "no", "off", "n", ""})


class Secret:
    """A string that refuses to render itself.

    ``repr``, ``str`` and ``format`` all yield :data:`REDACTED`, and attempting
    to JSON-serialise it raises. The value is reachable only through the
    explicitly-named :meth:`reveal`, so every place a credential actually
    escapes is grep-able in one search.

    Equality compares the underlying value, so ``Secret("") == Secret("")``, but
    the value never appears in a traceback, a log line or an error context.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str | None) -> None:
        self._value = value or ""

    def reveal(self) -> str:
        """Return the underlying value. The only way to get it out."""
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __len__(self) -> int:
        return len(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Secret):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(("aleph.Secret", self._value))

    def __str__(self) -> str:
        return REDACTED

    def __repr__(self) -> str:
        return f"Secret({REDACTED})" if self._value else "Secret(unset)"

    def __format__(self, spec: str) -> str:
        return REDACTED

    def __reduce__(self) -> tuple[Any, ...]:
        raise TypeError(
            "Secret refuses to be pickled or copied into a serialisable payload; "
            "call .reveal() at the exact point the credential is used"
        )


def _env(name: str, default: str | None = None) -> str | None:
    """Read ``ALEPH_<name>``, treating an empty string as unset."""
    raw = os.environ.get(f"{ENV_PREFIX}{name}")
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


def _env_first(names: tuple[str, ...], default: str | None = None) -> str | None:
    """Read the first of several ``ALEPH_`` names that is set.

    Aliases exist because ``.env.example`` documents some settings under a
    longer operational name (``FETCH_TIMEOUT_SECONDS``) than the library's own
    field (``REQUEST_TIMEOUT``). Honouring both means a correct ``.env`` never
    silently fails to apply.
    """
    for name in names:
        value = _env(name)
        if value is not None:
            return value
    return default


def _env_int(names: tuple[str, ...], default: int) -> int:
    raw = _env_first(names)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(names: tuple[str, ...], default: float) -> float:
    raw = _env_first(names)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(names: tuple[str, ...], default: bool) -> bool:
    raw = _env_first(names)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    return default


def _env_path(names: tuple[str, ...], default: str) -> Path:
    return Path(_env_first(names, default) or default).expanduser()


def _env_csv(names: tuple[str, ...], default: tuple[str, ...]) -> tuple[str, ...]:
    raw = _env_first(names)
    if raw is None:
        return default
    parts = tuple(item.strip() for item in raw.split(",") if item.strip())
    return parts or default


_EnumT = TypeVar("_EnumT", bound=Enum)


def _env_enum(names: tuple[str, ...], enum_cls: type[_EnumT], default: _EnumT) -> _EnumT:
    """Read an enum-valued setting, falling back to the safe default on garbage.

    A typo in an environment variable must not silently *enable* something: the
    defaults here are the conservative options (mock provider, manual
    retrieval), so falling back is always the cautious direction.
    """
    raw = _env_first(names)
    if raw is None:
        return default
    try:
        return enum_cls(raw.lower())
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Config:
    """Immutable snapshot of Aleph's runtime settings.

    Frozen because configuration must not drift mid-run: a pipeline that changed
    its retrieval mode or its model between phase 3 and phase 6 would produce a
    bundle whose ``methodology`` block was a lie.
    """

    # --- language model ----------------------------------------------------
    llm_provider: LLMProviderName = LLMProviderName.MOCK
    """Which provider to load. ``mock`` is deterministic, offline and the default."""

    qwen_base_url: str = ""
    """OpenAI-compatible endpoint for the Qwen provider. Empty when unconfigured."""

    qwen_api_key: Secret = field(default_factory=lambda: Secret(""))
    """Credential for that endpoint. Never logged, never serialised, never
    returned by the API."""

    qwen_model: str = "nvidia/Qwen3.5-122B-A10B-NVFP4"
    """Model identifier requested from the endpoint. Recorded in every bundle's
    ``methodology.model_provider``: a reader is entitled to know which model
    judged these claims."""

    qwen_revision: str = "98915d837c4e7c87ac8296d02e89de19b3207e6d"
    """Immutable Hugging Face revision of the local checkpoint. This is stored
    with every run so a moving model tag cannot silently change an analysis."""

    llm_temperature: float = 0.0
    """Kept at zero so two analyses of the same text can be meaningfully diffed."""

    llm_max_retries: int = 3
    """Retries on transient provider failures before a phase is marked failed."""

    # --- retrieval ---------------------------------------------------------
    retrieval_mode: RetrievalMode = RetrievalMode.MANUAL
    """``manual`` (default) forbids any outbound fetch during a pipeline run."""

    search_provider: str = "mock"
    """``none`` | ``mock`` | ``http``. Mock returns deterministic fixtures."""

    search_base_url: str = ""
    search_api_key: Secret = field(default_factory=lambda: Secret(""))
    search_max_results: int = 20

    # --- outbound HTTP -----------------------------------------------------
    request_timeout: float = 30.0
    """Per-request timeout in seconds for document and article fetches."""

    fetch_delay_seconds: float = 1.0
    """Minimum delay between requests to one host. Politeness, not performance."""

    user_agent: str = "Aleph/0.1 (+https://github.com/Mezosky/Aleph)"
    """Identifies the crawler honestly and gives operators a way to make contact.
    Anonymous crawling of public-interest sources is not acceptable behaviour."""

    max_pdf_mb: int = 50
    """Largest accepted document, in megabytes. Anything larger is refused with
    :class:`~aleph.core.errors.UnsupportedDocumentError` rather than truncated,
    because a silently truncated document produces a confidently incomplete
    analysis."""

    # --- filesystem --------------------------------------------------------
    data_dir: Path = Path("./data")
    """Root for working data: raw downloads, intermediates, finished bundles."""

    cache_dir: Path = Path("./data/cache")
    """On-disk HTTP and extraction cache. Conditional requests are served from
    here so a re-run costs a source nothing."""

    schema_dir: Path = Path("./schemas")
    """The JSON Schema contract, served by ``GET /v1/schemas/{name}``."""

    static_out_dir: Path = Path("./frontend/public/data")
    """Where the static export writes the site payload."""

    source_registry_path: Path = Path("./aleph/news/sources.yaml")
    """Registry of sources and jurisdiction configuration. All jurisdiction
    detail lives in data files, never in library code."""

    # --- API ---------------------------------------------------------------
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    """Explicit browser origins permitted to call the API. Never ``*`` with
    credentials."""

    api_host: str = "0.0.0.0"  # noqa: S104 - bind address is deployment config
    api_port: int = 8000
    max_upload_mb: int = 50
    max_concurrent_jobs: int = 2

    database_url: Secret = field(default_factory=lambda: Secret("sqlite:///./data/aleph.db"))
    """SQLAlchemy database URL. Wrapped because a PostgreSQL URL normally
    contains a password and configuration objects are safe to log."""

    database_auto_create: bool = True
    """Create missing tables on boot for local use. Production containers also
    run Alembic; this remains a safe idempotent guard for fresh installations."""

    # --- run behaviour -----------------------------------------------------
    env: str = "development"
    log_level: str = "info"
    seed: int = 20260807
    """Fixed seed for every stochastic step, so the same document yields the
    same bundle."""

    # -- derived helpers ----------------------------------------------------

    @property
    def max_pdf_bytes(self) -> int:
        """The document size limit in bytes."""
        return self.max_pdf_mb * 1024 * 1024

    @property
    def network_allowed_by_default(self) -> bool:
        """Whether a pipeline run may fetch without an explicit opt-in.

        True only in ``auto`` mode. Under ``manual`` and ``on_demand`` a fetch
        requires a deliberate call that passes ``allow_network=True``.
        """
        return self.retrieval_mode is RetrievalMode.AUTO

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    def to_public_dict(self) -> dict[str, Any]:
        """Render as a mapping safe to log or return from a diagnostics endpoint.

        Secrets are replaced with a boolean saying only whether one is
        configured. Paths become strings; enums become their values. Nothing
        here can leak a credential even if the whole mapping is dumped into a
        log line or an error response.
        """
        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, Secret):
                out[f"{f.name}_configured"] = bool(value)
            elif isinstance(value, Path):
                out[f.name] = str(value)
            elif isinstance(value, tuple):
                out[f.name] = list(value)
            else:
                out[f.name] = str(value) if hasattr(value, "value") else value
        return out

    def __repr__(self) -> str:
        """Redacted by construction: :class:`Secret` renders as ``***redacted***``."""
        shown = ", ".join(f"{k}={v!r}" for k, v in sorted(self.to_public_dict().items()))
        return f"Config({shown})"


def load_config(environ: dict[str, str] | None = None) -> Config:
    """Build a :class:`Config` from the environment.

    Unset and malformed values fall back to the safe default rather than
    raising: a typo in ``ALEPH_LLM_TEMPERATURE`` must not take down an analysis,
    and every default is chosen to be the conservative option (mock provider,
    manual retrieval, no network).

    Args:
        environ: Optional mapping to read instead of ``os.environ``. Used by
            tests; the values are applied to the process environment for the
            duration of the call, so precedence rules stay in one place.

    Returns:
        A frozen configuration snapshot. Not cached — see :func:`get_config`.
    """
    if environ is not None:
        saved = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update(environ)
            return _load_from_process_env()
        finally:
            os.environ.clear()
            os.environ.update(saved)
    return _load_from_process_env()


def _load_from_process_env() -> Config:
    data_dir = _env_path(("DATA_DIR",), "./data")
    return Config(
        llm_provider=_env_enum(("LLM_PROVIDER",), LLMProviderName, LLMProviderName.MOCK),
        qwen_base_url=_env_first(("QWEN_BASE_URL",), "") or "",
        qwen_api_key=Secret(_env_first(("QWEN_API_KEY",), "")),
        qwen_model=(
            _env_first(("QWEN_MODEL",), "nvidia/Qwen3.5-122B-A10B-NVFP4")
            or "nvidia/Qwen3.5-122B-A10B-NVFP4"
        ),
        qwen_revision=(
            _env_first(
                ("QWEN_REVISION",),
                "98915d837c4e7c87ac8296d02e89de19b3207e6d",
            )
            or "98915d837c4e7c87ac8296d02e89de19b3207e6d"
        ),
        llm_temperature=_env_float(("LLM_TEMPERATURE",), 0.0),
        llm_max_retries=_env_int(("LLM_MAX_RETRIES",), 3),
        retrieval_mode=_env_enum(("RETRIEVAL_MODE",), RetrievalMode, RetrievalMode.MANUAL),
        search_provider=_env_first(("SEARCH_PROVIDER",), "mock") or "mock",
        search_base_url=_env_first(("SEARCH_BASE_URL",), "") or "",
        search_api_key=Secret(_env_first(("SEARCH_API_KEY",), "")),
        search_max_results=_env_int(("SEARCH_MAX_RESULTS",), 20),
        request_timeout=_env_float(("REQUEST_TIMEOUT", "FETCH_TIMEOUT_SECONDS"), 30.0),
        fetch_delay_seconds=_env_float(("FETCH_DELAY_SECONDS",), 1.0),
        user_agent=_env_first(
            ("USER_AGENT", "HTTP_USER_AGENT"),
            "Aleph/0.1 (+https://github.com/Mezosky/Aleph)",
        )
        or "Aleph/0.1 (+https://github.com/Mezosky/Aleph)",
        max_pdf_mb=_env_int(("MAX_PDF_MB", "MAX_UPLOAD_MB"), 50),
        data_dir=data_dir,
        cache_dir=_env_path(("CACHE_DIR",), str(data_dir / "cache")),
        schema_dir=_env_path(("SCHEMA_DIR",), "./schemas"),
        static_out_dir=_env_path(("STATIC_OUT_DIR",), "./frontend/public/data"),
        source_registry_path=_env_path(("SOURCE_REGISTRY",), "./aleph/news/sources.yaml"),
        cors_origins=_env_csv(
            ("CORS_ORIGINS",),
            ("http://localhost:5173", "http://127.0.0.1:5173"),
        ),
        api_host=_env_first(("API_HOST",), "0.0.0.0") or "0.0.0.0",  # noqa: S104
        api_port=_env_int(("API_PORT",), 8000),
        max_upload_mb=_env_int(("MAX_UPLOAD_MB", "MAX_PDF_MB"), 50),
        max_concurrent_jobs=_env_int(("MAX_CONCURRENT_JOBS",), 2),
        database_url=Secret(_env_first(("DATABASE_URL",), "sqlite:///./data/aleph.db")),
        database_auto_create=_env_bool(("DATABASE_AUTO_CREATE",), True),
        env=_env_first(("ENV",), "development") or "development",
        log_level=(_env_first(("LOG_LEVEL",), "info") or "info").lower(),
        seed=_env_int(("SEED",), 20260807),
    )


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the process-wide configuration snapshot.

    Cached so that every module sees identical settings for the whole life of a
    run. A pipeline whose configuration shifted between phases would emit a
    ``methodology`` block that did not describe how the bundle was actually
    produced, which is worse than no methodology block at all.
    """
    return load_config()


def reset_config_cache() -> None:
    """Drop the cached configuration so the next call re-reads the environment.

    For tests and for long-lived processes that legitimately reload settings.
    Never call this mid-analysis.
    """
    get_config.cache_clear()
